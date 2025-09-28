import os, io, math, json, datetime, pandas as pd, numpy as np
import streamlit as st
from PIL import Image, ImageDraw
import folium
from streamlit_folium import st_folium
import ee
import geemap.foliumap as geemap

# ------------ CONFIG ------------
DEFAULT_AOI = [78.2, 17.1, 78.7, 17.65]  # Hyderabad-ish
PROJECT_ID = st.secrets["ee"].get("PROJECT_ID", "garbage-detection-471720")
SERVICE_ACCOUNT = st.secrets["ee"]["SERVICE_ACCOUNT"]
PRIVATE_KEY = st.secrets["ee"]["PRIVATE_KEY"]  # full JSON string

# ------------ EE INIT (Service Account) ------------
credentials = ee.ServiceAccountCredentials(SERVICE_ACCOUNT, PRIVATE_KEY)
ee.Initialize(credentials, project=PROJECT_ID)

# ------------ HELPERS ------------
def month_seq(start, end):
    s = ee.Date(start); e = ee.Date(end)
    n = e.difference(s, 'month').int()
    return ee.List.sequence(0, n.subtract(1)).map(lambda k: s.advance(ee.Number(k),'month'))

def s2_monthly(aoi, d, cloudy=60, loosen=False):
    d = ee.Date(d)
    ic = (ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
          .filterBounds(aoi).filterDate(d, d.advance(1,'month'))
          .filter(ee.Filter.lte("CLOUDY_PIXEL_PERCENTAGE", cloudy)))
    def mask(i):
        scl = i.select('SCL')
        good = scl.eq(4).Or(scl.eq(5)).Or(scl.eq(6)).Or(scl.eq(7)).Or(scl.eq(11))
        if loosen: good = good.Or(scl.eq(3)).Or(scl.eq(8))
        return i.updateMask(good)
    m = ic.map(mask).median().clip(aoi)
    ndvi = m.normalizedDifference(['B8','B4']).rename('NDVI')
    ndbi = m.normalizedDifference(['B11','B8']).rename('NDBI')
    ndwi = m.normalizedDifference(['B3','B8']).rename('NDWI')
    return m.addBands([ndvi, ndbi, ndwi])

def s1_monthly(aoi, d):
    d = ee.Date(d)
    ic = (ee.ImageCollection("COPERNICUS/S1_GRD")
          .filterBounds(aoi).filterDate(d, d.advance(1,'month'))
          .filter(ee.Filter.listContains('transmitterReceiverPolarisation','VV'))
          .filter(ee.Filter.listContains('transmitterReceiverPolarisation','VH')))
    def to_db(i): return i.select(['VV','VH']).log10().multiply(10).rename(['VV','VH'])
    return ic.map(to_db).median().clip(aoi)

def period_stack(aoi, start, end):
    months = month_seq(start, end)
    def mstack(d):
        s2 = s2_monthly(aoi, d).select(['B4','B3','B2','NDVI','NDBI','NDWI'])
        s1 = s1_monthly(aoi, d).select(['VV','VH'])
        return s2.addBands(s1)
    return ee.ImageCollection(ee.List(months).map(lambda m: mstack(m))).median()

def debris_mask_from_pre_post(pre, post, qlow=35, qhigh=65, fb={'NDVI_MAX':0.30,'NDBI_MIN':0.015,'NDWI_MAX':0.15,'VV_MIN_DB':-13}):
    AOI = pre.geometry()
    qbands = ['NDVI','NDBI','NDWI','VV']
    qpre  = pre.select(qbands).reduceRegion(ee.Reducer.percentile([qlow, qhigh]), AOI, 1000, bestEffort=True, maxPixels=1e9)
    qpost = post.select(qbands).reduceRegion(ee.Reducer.percentile([qlow, qhigh]), AOI, 1000, bestEffort=True, maxPixels=1e9)
    G = lambda q,k,fbv: ee.Number(ee.Algorithms.If(q.get(k), q.get(k), fbv))
    ndvi_drop = post.select('NDVI').lt(G(qpre, f'NDVI_p{qlow}',  fb['NDVI_MAX']))
    ndbi_rise = post.select('NDBI').gt(G(qpost,f'NDBI_p{qhigh}', fb['NDBI_MIN']))
    ndwi_drop = post.select('NDWI').lt(G(qpre, f'NDWI_p{qlow}',  fb['NDWI_MAX']))
    vv_rise   = post.select('VV')  .gt(G(qpost,f'VV_p{qhigh}',   fb['VV_MIN_DB']))
    m = ndvi_drop.And(ndbi_rise).And(ndwi_drop).And(vv_rise).selfMask()
    return m.connectedPixelCount(100, True).gte(15).selfMask()

def to_vec(mask_img, aoi):
    vec_raw = mask_img.reduceToVectors(geometry=aoi, geometryType='polygon', scale=10, maxPixels=1e13)
    def add_attrs(f):
        g = f.geometry()
        area_m2 = g.area(10); perim = g.perimeter(10)
        area_ha = area_m2.divide(10000)
        compact = ee.Number(4*math.pi).multiply(area_m2).divide(perim.pow(2))
        cen = g.centroid(10).coordinates()
        return f.set({'area_ha': area_ha, 'compact': compact, 'lon': cen.get(0), 'lat': cen.get(1)})
    return ee.FeatureCollection(vec_raw.map(add_attrs))

# ------------ UI ------------
st.set_page_config(page_title="Civic Risk Dashboard", layout="wide", page_icon="🗺️")
st.title("🗺️ Civic Risk Dashboard — Landfills, Water, Flood (Hyderabad demo)")

with st.sidebar:
    st.subheader("Area of Interest")
    lon1, lat1, lon2, lat2 = st.text_input("AOI lon1,lat1,lon2,lat2", ",".join(map(str, DEFAULT_AOI))).split(",")
    AOI = ee.Geometry.Rectangle([float(lon1), float(lat1), float(lon2), float(lat2)]).buffer(2000)

    st.subheader("Windows (YYYY-MM-DD)")
    pre_start  = st.text_input("PRE start",  "2023-10-01")
    pre_end    = st.text_input("PRE end",    "2023-12-31")
    post_start = st.text_input("POST start", "2024-10-01")
    post_end   = st.text_input("POST end",   "2024-12-31")

    qlow  = st.slider("Low quantile",  10, 49, 35)
    qhigh = st.slider("High quantile", 51, 90, 65)
    ndwi_thr = st.slider("Water NDWI >", 0.0, 0.5, 0.20, 0.01)
    near_water_m = st.slider("Garbage-near-water buffer (m)", 10, 200, 50, 5)

    if st.button("Compute / Refresh"):
        st.session_state["go"] = True

# ------------ Compute ------------
if st.session_state.get("go", True):
    # stacks
    pre  = period_stack(AOI, pre_start,  pre_end)
    post = period_stack(AOI, post_start, post_end)

    # masks
    debris = debris_mask_from_pre_post(pre, post, qlow, qhigh)
    water  = post.select('NDWI').gt(ndwi_thr).selfMask()
    near   = debris.focal_max(kernel=ee.Kernel.circle(near_water_m, 'meters')).And(water.unmask(0)).selfMask()

    # vectors
    debris_vec = to_vec(debris, AOI)
    near_vec   = to_vec(near, AOI)

    # map
    m = geemap.Map(center=[(float(lat1)+float(lat2))/2,(float(lon1)+float(lon2))/2], zoom=11, draw_export=False)
    m.add_basemap('HYBRID')
    m.add_layer(geemap.ee_tile_layer(pre.select(['B4','B3','B2']).visualize(min=0,max=3000), {}, "PRE (RGB)"))
    m.add_layer(geemap.ee_tile_layer(post.select(['B4','B3','B2']).visualize(min=0,max=3000), {}, "POST (RGB)"))
    m.add_layer(geemap.ee_tile_layer(debris.visualize(palette=['#ff0000'], min=0, max=1), {}, "Debris"))
    m.add_layer(geemap.ee_tile_layer(water.visualize(palette=['#81d4fa'], min=0, max=1), {}, "Water"))
    m.add_layer(geemap.ee_tile_layer(near.visualize(palette=['#9c27b0'], min=0, max=1), {}, "Garbage near water"))
    st_data = st_folium(m, width=1200, height=700)

    # simple table
    st.subheader("Debris candidate polygons (sample)")
    try:
        gdf = geemap.ee_to_gdf(debris_vec.limit(50))
        st.dataframe(gdf[["area_ha","compact","geometry"]].head(20))
    except Exception:
        st.info("Large AOI — download the GeoJSON export instead.")

    # export buttons
    if st.button("Queue GeoJSON export (Drive)"):
        ee.batch.Export.table.toDrive(
            collection=debris_vec,
            description='debris_sites_geojson',
            folder='gee_civic_outputs',
            fileNamePrefix='debris_sites_geojson',
            fileFormat='GeoJSON').start()
        st.success("Export queued → Drive/gee_civic_outputs")

import os, json, streamlit as st, ee, geemap.foliumap as geemap

def _get_ee_cfg():
    ee_secrets = st.secrets.get("ee", {})
    return {
        "PROJECT_ID": ee_secrets.get("PROJECT_ID", "garbage-detection-471720"),
        "SERVICE_ACCOUNT": ee_secrets.get("SERVICE_ACCOUNT"),
        "PRIVATE_KEY": ee_secrets.get("PRIVATE_KEY"),
    }

CFG = _get_ee_cfg()

def init_ee(cfg):
    if not (cfg["SERVICE_ACCOUNT"] and cfg["PRIVATE_KEY"]):
        st.error("Missing SERVICE_ACCOUNT/PRIVATE_KEY in secrets. Add them in Settings → Secrets.")
        st.stop()
    key_json = cfg["PRIVATE_KEY"]
    if isinstance(key_json, dict):
        key_json = json.dumps(key_json)
    creds = ee.ServiceAccountCredentials(cfg["SERVICE_ACCOUNT"], key_data=key_json)
    ee.Initialize(creds, project=cfg["PROJECT_ID"])
    st.caption(f"EE ready · project: {cfg['PROJECT_ID']} · SA: {cfg['SERVICE_ACCOUNT']}")

init_ee(CFG)
