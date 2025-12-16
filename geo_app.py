import streamlit as st
import folium
from streamlit_folium import st_folium
import exiftool
import os
import shutil
import math
import random
import time
from zipfile import ZipFile
import tempfile
import geocoder  # Using this for everything now (more reliable)

# --- CONFIGURATION ---
ALLOWED_TYPES = ["image/jpeg", "image/webp"]
MAX_FILES = 25

# --- HELPER FUNCTIONS ---
def get_random_point_in_radius(lat, lon, radius_km):
    if radius_km <= 0:
        return lat, lon
    radius_earth_km = 6371
    r = radius_km / radius_earth_km
    u = random.random()
    v = random.random()
    w = r * math.sqrt(u)
    t = 2 * math.pi * v
    x = w * math.cos(t)
    y = w * math.sin(t)
    new_lat = x / math.pi * 180 + lat
    new_lon = y / math.pi * 180 / math.cos(math.radians(lat)) + lon
    return new_lat, new_lon

@st.cache_data
def get_current_location():
    """Finds the user's location via IP address to center the map."""
    try:
        g = geocoder.ip('me')
        if g.latlng:
            return g.latlng
    except:
        pass
    # Fallback to Los Angeles
    return [34.0522, -118.2437] 

def process_images(files, targets):
    temp_dir = tempfile.mkdtemp()
    processed_paths = []
    
    try:
        file_map = {} 
        for i, uploaded_file in enumerate(files):
            file_path = os.path.join(temp_dir, uploaded_file.name)
            with open(file_path, "wb") as f:
                f.write(uploaded_file.getbuffer())
            file_map[i] = file_path

        with exiftool.ExifToolHelper() as et:
            for i, file_path in file_map.items():
                lat, lon = targets[i]
                
                # N/S and E/W Reference logic
                lat_ref = "N" if lat >= 0 else "S"
                lon_ref = "E" if lon >= 0 else "W"

                try:
                    et.set_tags(
                        [file_path],
                        tags={
                            "GPSLatitude": abs(lat),
                            "GPSLatitudeRef": lat_ref,
                            "GPSLongitude": abs(lon),
                            "GPSLongitudeRef": lon_ref
                        }
                    )
                    processed_paths.append(file_path)
                except Exception as e:
                    st.error(f"Error processing {os.path.basename(file_path)}: {e}")

        zip_path = os.path.join(temp_dir, "geotagged_images.zip")
        with ZipFile(zip_path, 'w') as zipf:
            for p in processed_paths:
                if not p.endswith("_original"):
                    zipf.write(p, os.path.basename(p))
        
        with open(zip_path, "rb") as f:
            zip_data = f.read()
            
    finally:
        shutil.rmtree(temp_dir)
        
    return zip_data

# --- MAIN APP UI ---
st.set_page_config(page_title="GeoTag Pro", page_icon="📍")
st.title("📍 GeoTag Pro")
st.markdown("Add GPS coordinates to JPEG/WebP images without re-compressing them.")

uploaded_files = st.file_uploader("1. Upload Images (Max 10)", type=['jpg', 'jpeg', 'webp'], accept_multiple_files=True)

if uploaded_files and len(uploaded_files) > MAX_FILES:
    st.error(f"Please select only {MAX_FILES} files maximum.")
    st.stop()

mode = st.radio("2. Choose Location Method", ["Pin on Map", "List of Cities"])

final_targets = [] 

if mode == "Pin on Map":
    col1, col2 = st.columns([3, 1])
    
    with col1:
        st.info("Click on the map to set the center point.")
        
        # AUTO-LOCATION
        start_lat, start_lon = get_current_location()
        
        m = folium.Map(location=[start_lat, start_lon], zoom_start=12)
        m.add_child(folium.LatLngPopup())
        
        map_data = st_folium(m, height=400, width=700)
    
    clicked_lat = start_lat
    clicked_lon = start_lon
    
    if map_data.get("last_clicked"):
        clicked_lat = map_data["last_clicked"]["lat"]
        raw_lon = map_data["last_clicked"]["lng"]
        # Normalize longitude logic
        clicked_lon = ((raw_lon + 180) % 360) - 180
        
    with col2:
        st.write("**Selected Location:**")
        st.write(f"Lat: {clicked_lat:.4f}")
        st.write(f"Lon: {clicked_lon:.4f}")
        
        radius = st.slider("Random Radius (km)", 0.0, 50.0, 0.0, step=0.5)
        st.caption("Images will be scattered randomly within this radius.")

    if uploaded_files:
        for _ in uploaded_files:
            final_targets.append(get_random_point_in_radius(clicked_lat, clicked_lon, radius))

elif mode == "List of Cities":
    city_input = st.text_area("Enter cities (comma separated)", "Monterey Park CA, Arcadia CA, Pasadena CA")
    
    if uploaded_files:
        # Robust parsing: handles commas AND newlines
        raw_text = city_input.replace("\n", ",")
        city_names = [c.strip() for c in raw_text.split(',') if c.strip()]
        
        if not city_names:
            st.warning("Please enter at least one city.")
        else:
            unique_coords = {}
            failed_cities = []
            
            with st.spinner("Finding coordinates (using ArcGIS)..."):
                unique_cities = list(set(city_names))
                
                for city in unique_cities:
                    try:
                        # SWITCHED TO ARCGIS (More robust, no User-Agent needed)
                        g = geocoder.arcgis(city)
                        if g.ok:
                            unique_coords[city] = g.latlng
                        else:
                            failed_cities.append(city)
                    except Exception as e:
                        failed_cities.append(city)
                        print(f"Error looking up {city}: {e}")
                    
                    # Small courtesy delay
                    time.sleep(0.5)
            
            if failed_cities:
                st.warning(f"Could not find: {', '.join(failed_cities)}")

            if not unique_coords:
                st.error("Could not find coordinates. Please check your internet connection.")
            else:
                st.success(f"Ready to tag locations: {', '.join(unique_coords.keys())}")
                for i in range(len(uploaded_files)):
                    city = city_names[i % len(city_names)]
                    if city in unique_coords:
                        final_targets.append(unique_coords[city])
                    elif len(unique_coords) > 0:
                        final_targets.append(list(unique_coords.values())[0])

if uploaded_files and final_targets:
    if st.button("Tag Images & Download"):
        with st.spinner("Processing metadata..."):
            try:
                zip_bytes = process_images(uploaded_files, final_targets)
                
                st.download_button(
                    label="Download Geotagged Images (ZIP)",
                    data=zip_bytes,
                    file_name="geotagged_images.zip",
                    mime="application/zip"
                )
                st.balloons()
                st.success("Done! Images processed.")
            except Exception as e:
                st.error(f"Error: {e}")
