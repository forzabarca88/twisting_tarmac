import streamlit as st
import pydeck as pdk
import pandas as pd
import requests
import os
import json

API_URL = os.getenv("API_URL", "http://localhost:8000")

st.set_page_config(layout="wide", page_title="TwistingTarmac — Fun-to-Drive Roads")

st.title("🚗 TwistingTarmac")
st.markdown("Find the best driving roads in Australia.")

# Sidebar filters
with st.sidebar:
    st.header("Filters")
    state = st.selectbox("State", ["All", "NSW", "VIC", "QLD", "WA", "SA", "TAS", "ACT", "NT"])
    metric = st.selectbox("Metric", ["Fun Score", "Curvature", "Speed", "Elevation"])
    limit = st.slider("Number of roads", 5, 20, 5)

# Layout
col1, col2 = st.columns([1, 2])

# Fetch data for top roads
try:
    response = requests.get(f"{API_URL}/api/top-roads", params={"limit": limit})
    if response.status_code == 200:
        top_roads = response.json()
    else:
        top_roads = []
        st.error(f"Failed to fetch data: {response.status_code}")
except Exception as e:
    top_roads = []
    st.error(f"Connection error: {e}")

# Fetch segments for the map
# For the PoC, we'll use a fixed bbox or default to Australia
try:
    # A generic bbox for Australia or a default
    # In a real app, this would be viewport-driven
    bbox = "112.9,-43.7,153.6,-10.0"
    response = requests.get(f"{API_URL}/api/segments", params={"bbox": bbox})
    if response.status_code == 200:
        segments_geojson = response.json()
    else:
        segments_geojson = {"type": "FeatureCollection", "features": []}
except Exception:
    segments_geojson = {"type": "FeatureCollection", "features": []}

with col1:
    st.subheader(f"Top {limit} Roads")
    if not top_roads:
        st.write("No data available yet. Please run the ingest pipeline.")
    else:
        for idx, road in enumerate(top_roads):
            st.metric(label=f"{idx+1}. {road['name'] or 'Road'}", value=f"{road['score']:.2f}", delta=f"{road['length_km']:.1f} km")

with col2:
    st.subheader("Interactive Map")
    
    # Layer for segments
    # Color segments by score
    # score is 0-1, map to red-green
    # This is a bit complex in pydeck without a specific mapping
    # For PoC, just show them as lines
    
    view_state = pdk.ViewState(
        latitude=-25.2744,
        longitude=133.7751,
        zoom=3,
        pitch=0,
    )

    layer = pdk.Layer(
        "GeoJsonLayer",
        segments_geojson,
        opacity=0.8,
        stroked=True,
        filled=True,
        get_line_color="[255, 0, 0]", # Red for PoC
        get_line_width=1000,
        pickable=True,
    )

    r = pdk.Deck(
        layers=[layer],
        initial_view_state=view_state,
        tooltip={"text": "Road ID: {id}\nScore: {score}"}
    )
    
    st.pydeck_chart(r)

st.markdown("---")
st.info("Run `python scripts/ingest_pbf.py` and `python scripts/compute_metrics.py` to populate data.")
