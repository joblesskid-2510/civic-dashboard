# ---------------------------------------------------------------
# Civic Risk Mini-Dashboard (Streamlit + EE, fast & reliable)
# - No geemap (avoids heavy deps); uses Folium tiles directly
# - Renders UI immediately; only computes after a button click
# - Layers: PRE/POST RGB, Debris/Landfill, Water (NDWI), Near-water garbage
# - Drive export for debris polygons
# ---------------------------------------------------------------

import json, math
import streamlit as st
from streamlit_folium import st_folium
import folium
import ee

# ========= YOUR SERVICE ACCOUNT KEY (as JSON string) =========
KEY_JSON = r'''{
  "type": "service_account",
  "project_id": "garbage-detection-471720",
  "private_key_id": "7b9bc725548da94b4d03564c66fb360b420c41b2",
  "private_key": "-----BEGIN PRIVATE KEY-----\nMIIEvgIBADANBgkqhkiG9w0BAQEFAASCBKgwggSkAgEAAoIBAQDMZguFOkN/EiGn\n1U5TdldAB8jyfMyP+ETbYkf/QncLFL7BohWscJbxuM2S292hnYuF9WFO+jAhBH8E\nvkGSDdagdwTj/WrmhWYjwvbJw1IfuAF1pomaXtl9PIfIY2XkeMtwdNXYUDJ/f2in\ndADxSJlpuFga6syIFSrgdHS0+kGxIzfqm+kWVjLs/REiB6f9I4IXqb/PmTrDT8BC\npVCX6ocBrELOwO7zrzg28wKMaEg4npUuzAgQLFrxXtuH0MLMF546U5Dv9fXYxr6a\n49zH8zBJyhqRZXdeKIwgfanwSHhgzMasrS1wO0bN9SBo0oihPQ8sSQBghYnVb2Tr\n5hfhkrKzAgMBAAECggEASfIi+dRtxcNr/JltSEGYaBhI6P0gTnd9hbbFIEJN6erb\n5hZ669MhsJpweNBlGopyBwkSZq2ZiuBjCXbBJxMtkgjs8oRkT7h0Dr0CZlTs2X/K\nu2MABiKJYUbsQqE/JAxVYT5LfQHqevi/hlEv5BqlMbuY2EgYraSmyeQnsq+U432Z\n1Iu1Mrf7c7b70AgR/waieIsRBpuUXCoPcpFtEcW/ABQ67x+RYnJe7sPbSbdEN6Lm\nLvcysklt6Zrxinpi6fDp7zxguZLZNHw3EDD8v3swVpErl8A8lL+Gk4wEzicG29LQ\nh9srEZS2HaiJN4nYPlfzrYF07Kd8BnQE37MX7vLCRQKBgQD10iPP+TeNEnzSckyg\njhgBWLYFP83pEpaEBH2TieIY+LsbRyOUxSv6Mjg7qaWlCQ1sKlhuw8mnyJe9j6dP\n983RfAUe2GHhTAf4R6bD1NA9r6y360s3Kun85eAQFTlEpLnvvZfqMn29hq0JwK2S\ngPfDk1JVuDd5cP+ov61yZkD+ZQKBgQDU3M1xdWLdHiAhwpmo1OfjSp7z2cFHJOHn\nAc4EL4iifYpLEMB8nqVY1nAtZ+sMGtRWg3ZRaOOjxy/6vQqwI3Y3T8wng+hVnzLi\nMxVlbuWDPDtNmEdC6navoY0dclkw3Tr8Wa7o70zIXmsvyW/3t3VnF+w/eInUtIfi\nnUfhSxGvNwKBgDeIGkkAPrlixMnxwje/AdNEDBKRgF23skLulMPAsU/82J/n6TTR\negbSU3u+7kmjCuI1irazChoaKZVMH3rkOx2oy6tVLH9t4psG7LhumgBlcDo4MEyt\nKCDWeVCIyuAj6lErXmcsstUe2HZMjal78vy+iioNLJMFoOupKXCfgu01AoGBALoF\ncIDbvhdQ8XGvd8ukrDXlC349aXw8DjNsT1c3Fygxn/6z2BPQLN2zIPt9WlsMw04L\nuwWwLWf+db6hIEsH4pK56McLrqnM45HsZKFtRaPnqkfIcVZYQnqAKyt1t95NJ/RK\nh+HG5wogAXoUhwYrzKzYqjxZodJCJpJzMtL/YKgHAoGBAOcLt+aW/2FWHWmRZooh\nVn7oyqgyiTEu/ElJOIJDN7pxkunZ60rrHZGNAl6aoyhCx5qULe5yvX0fGXfYmxCn\n1dhKDh5TyOGGAaEavyS+jfgzw30qlA0WbyKcg8MaTKkNQsxqh06+nHZ74gw//aLl\nXu/BFRd6pGdKjwNRfysrGh2H\n-----END PRIVATE KEY-----\n",
  "client_email": "civic-dashboard@garbage-detection-471720.iam.gserviceaccount.com",
  "client_id": "107955791999220600617",
  "auth_uri": "https://accounts.google.com/o/oauth2/auth",
  "token_uri": "https://oauth2.googleapis.com/token",
  "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
  "client_x509_cert_url": "https://www.googleapis.com/robot/v1/metadata/x509/civic-dashboard%40garbage-detection-471720.iam.gserviceaccount.com",
  "universe_domain": "googleapis.com"
}'''
SERVICE_ACCOUNT = "civic-dashboard@garbage-detection-471720.iam.gserviceaccount.com"
PROJECT_ID      = "garbage-detection-471720"

# ========= INIT EE EARLY, BUT LIGHTWEIGHT =========
creds = ee.ServiceAccountCredentials(SERVICE_ACCOUNT, key_data=KEY_JSON)
ee.Initialize(creds, project=PROJECT_ID)

# ========= SMALL EE HELPERS =========
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
        d = ee.Date(d)
        s2 = s2_monthly(aoi, d).select(['B4','B3','B2','NDVI','NDBI','NDWI'])
        s1 = s1_monthly(aoi, d).select(['VV','VH'])
        return s2.addBands(s1)
    return ee.ImageCollection(ee.List(months).map(mstack)).median()

def debris_mask_from_pre_post(pre, post, qlow=35, qhigh=65,
                              fb={'NDVI_MAX':0.30,'NDBI_MIN':0.015,'NDWI_MAX':0.15,'VV_MIN_DB':-13}):
    aoi = pre.geometry()
    qbands = ['NDVI','NDBI','NDWI','VV']
    qpre  = pre.select(qbands).reduceRegion(ee.Reducer.percentile([qlow, qhigh]), aoi, 1000, bestEffort=True, maxPixels=1e9)
    qpost = post.select(qbands).reduceRegion(ee.Reducer.percentile([qlow, qhigh]), aoi, 1000, bestEffort=True, maxPixels=1e9)
    G = lambda q,k,fbv: ee.Number(ee.Algorithms.If(q.get(k), q.get(k), fbv))
    ndvi_drop = post.select('NDVI').lt(G(qpre, f'NDVI_p{qlow}',  fb['NDVI_MAX']))
    ndbi_rise = post.select('NDBI').gt(G(qpost,f'NDBI_p{qhigh}', fb['NDBI_MIN']))
    ndwi_drop = post.select('NDWI').lt(G(qpre, f'NDWI_p{qlow}',  fb['NDWI_MAX']))
    vv_rise   = post.select('VV')  .gt(G(qpost,f'VV_p{qhigh}',   fb['VV_MIN_DB']))
    m = ndvi_drop.And(ndbi_rise).And(ndwi_drop).And(vv_rise).selfMask()
    return m.connectedPixelCount(100, True).gte(15).selfMask()

def ee_tile(image, vis, name):
    """Create a Folium tile layer from an ee.Image (non-blocking)."""
    info = image.getMapId(vis)
    return folium.TileLayer(tiles=info["tile_fetcher"].url_format,
                            attr="Google Earth Engine", name=name, overlay=True, control=True)

def to_vec(mask_img, aoi):
    vec_raw = mask_img.reduceToVectors(geometry=aoi, geometryType='polygon', scale=10, maxPixels=1e13)
    def add_attrs(f):
        g = f.geometry()
        area_m2 = g.area(10); perim = g.perimeter(10)
        area_ha = area_m2.divide(10000)
        compact = ee.Number(4*math.pi).multiply(area_m2).divide(perim.pow(2))
        return f.set({'area_ha': area_ha, 'compact': compact})
    return ee.FeatureCollection(vec_raw.map(add_attrs))

# ================== STREAMLIT UI ==================
st.set_page_config(page_title="Civic Risk (EE)", layout="wide", page_icon="🗺️")
st.title("🗺️ Civic Risk — Landfills & Water (Hyderabad demo)")

with st.sidebar:
    st.subheader("Area of Interest")
    aoi_str = st.text_input("AOI lon1,lat1,lon2,lat2", "78.2,17.1,78.7,17.65")
    try:
        lon1, lat1, lon2, lat2 = [float(x) for x in aoi_str.split(",")]
    except:
        st.stop()
    AOI = ee.Geometry.Rectangle([lon1, lat1, lon2, lat2]).buffer(2000)

    st.subheader("Windows (YYYY-MM-DD)")
    pre_start  = st.text_input("PRE start",  "2023-10-01")
    pre_end    = st.text_input("PRE end",    "2023-12-31")
    post_start = st.text_input("POST start", "2024-10-01")
    post_end   = st.text_input("POST end",   "2024-12-31")

    st.subheader("Thresholds")
    qlow  = st.slider("Low quantile",  10, 49, 35)
    qhigh = st.slider("High quantile", 51, 90, 65)
    ndwi_thr = st.slider("Water NDWI >", 0.0, 0.5, 0.20, 0.01)
    near_water_m = st.slider("Near-water buffer (m)", 10, 200, 50, 5)

    compute = st.button("Compute / Refresh", type="primary")

# Show a small “ready” note so users know the app didn’t crash
st.caption(f"EE ready · project: {PROJECT_ID} · SA: {SERVICE_ACCOUNT}")

# Only compute when the user clicks
if not compute:
    st.info("Set AOI & parameters in the sidebar, then click **Compute / Refresh**.")
    st.stop()

with st.spinner("Building composites & masks…"):
    pre  = period_stack(AOI, pre_start,  pre_end)
    post = period_stack(AOI, post_start, post_end)
    debris = debris_mask_from_pre_post(pre, post, qlow, qhigh)
    water  = post.select('NDWI').gt(ndwi_thr).selfMask()
    # Use float radius in meters (no Kernel object)
    near   = debris.focal_max(float(near_water_m), 'meters').And(water.unmask(0)).selfMask()

# ============== MAP (Folium, non-blocking tiles) ==============
m = folium.Map(location=[(lat1+lat2)/2, (lon1+lon2)/2], zoom_start=11, control_scale=True, tiles="CartoDB positron")

# PRE/POST
ee_tile(pre.select(['B4','B3','B2']),  {'min':0,'max':3000}, "PRE (RGB)").add_to(m)
ee_tile(post.select(['B4','B3','B2']), {'min':0,'max':3000}, "POST (RGB)").add_to(m)

# Overlays
ee_tile(debris, {'palette':['#ff0000'], 'min':0, 'max':1}, "Debris / Landfill").add_to(m)
ee_tile(water,  {'palette':['#81d4fa'], 'min':0, 'max':1}, "Water (NDWI)").add_to(m)
ee_tile(near,   {'palette':['#9c27b0'], 'min':0, 'max':1}, "Garbage near water").add_to(m)
folium.LayerControl(collapsed=False).add_to(m)

# Render
st_data = st_folium(m, width=1200, height=720)

# ============== EXPORTS (Drive) =================
st.subheader("Export")
if st.button("Queue debris polygons (GeoJSON) to Google Drive"):
    debris_vec = to_vec(debris, AOI)
    ee.batch.Export.table.toDrive(
        collection=debris_vec,
        description='debris_sites_geojson',
        folder='gee_civic_outputs',
        fileNamePrefix='debris_sites_geojson',
        fileFormat='GeoJSON'
    ).start()
    st.success("Export queued → Drive/gee_civic_outputs")
