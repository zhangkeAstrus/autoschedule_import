import streamlit as st
import pandas as pd
import requests
import re  # regex for extracting GVWR numbers
import time
import xml.etree.ElementTree as ET
import io

# VIN Cleaning Function
def clean_vin(vin):
    """Cleans up the VIN by trimming spaces and replacing O->0, I->1."""
    if pd.isna(vin):
        return vin
    return vin.strip().upper().replace("O", "0").replace("I", "1")

# Function to decode VINs using NHTSA API
def decode_vins(vins):
    url = "https://vpic.nhtsa.dot.gov/api/vehicles/DecodeVINValuesBatch/"
    batch_size = 50  # NHTSA API limit
    all_results = []
    for i in range(0, len(vins), batch_size):
        batch = vins[i: i + batch_size]
        params = {"format": "json", "data": ";".join(batch)}
        response = requests.post(url, data=params)
        if response.status_code == 200:
            results = response.json().get("Results", [])
            all_results.extend(results)
        else:
            st.error(f"Error fetching VIN data from NHTSA API for batch {i // batch_size + 1}")
    return pd.DataFrame(all_results) if all_results else pd.DataFrame()

# Function to extract weight (GVWR) from text
def extract_gvwr_weight(gvwr_text):
    """Extracts the first numeric weight value in pounds from GVWR text."""
    if pd.isna(gvwr_text) or gvwr_text.strip() == "":
        return None
    match = re.search(r"(\d{1,3}(?:,\d{3})*)\s*lb", gvwr_text)
    if match:
        return int(match.group(1).replace(",", ""))
    return None

# Function to determine Vehicle Type based on GVWR and VehicleType
def map_vehicle_type(vehicle_type, body_class, gvw):
    """Maps GVWR and VehicleType to the corresponding Vehicle Type category."""
    if vehicle_type == "TRAILER":
        return "Trailer"
    elif body_class == "Truck-Tractor":
        return "Truck Tractor"
    if gvw is None:
        return "Unknown"
    if gvw <= 10000:
        return "Light Truck"
    elif gvw <= 20000:
        return "Medium Truck"
    elif gvw <= 45000:
        return "Heavy Truck"
    else:
        return "Extra Heavy Truck"

# Function to map Vehicle Type to Class Code
def map_class_code(vehicle_type):
    """Maps Vehicle Type to its respective Class Code."""
    class_code_mapping = {
        "Private Passenger": "739800",
        "Light Truck": "014890",
        "Medium Truck": "214890",
        "Heavy Truck": "314890",
        "Extra Heavy Truck": "404890",
        "Truck Tractor": "504890",
        "Trailer": "684890"
    }
    return class_code_mapping.get(vehicle_type, "Unknown")

vehicle_schedule_fields = [
    "State", "Vehicle Sequence No", "City", "Zip", "Garage Territory", "Town Code",
    "County Code", "Tax Terr Code", "Vehicle Year", "Make", "Model", "Cleaned VIN",
    "Vehicle Type Code", "CompGroupNo", "Class Code", "Secondary Class Code",
    "Zone Territory (Garaged)", "Zone Territory (Destination)", "CO Private Pass Indiv Owned",
    "Auto Theft Prevention Surcharge", "GVW", "PIP", "Addt'l PIP", "Med Pay", "UM UIM",
    "UM PD", "OTC Coverage", "OTC Deductible", "ACV or Stated Amount", "Cost New",
    "Collision Coverage", "Collision Ded", "Misc Collision", "Auto Loan/Lease Gap Cov",
    "PIP - Operated by Employee", "Leased Vehicle", "Towing", "Rental Reimbursement Cov",
    "Rental Reimbursement Max Amt", "Rental Reimbursement Max Days #",
    "Vehicle Comp Deductible Override Factor", "Vehicle Collision Deductible Override Factor"
]

st.title("Vehicle Schedule Submission Review")
st.sidebar.title("Navigation")
page = st.sidebar.radio("Go to:", ["Upload & Preprocessing", "VIN Processing & Results"])

if page == "Upload & Preprocessing":
    uploaded_file = st.file_uploader("Upload an Excel file with vehicle submission data", type=["xlsx"])
    
    if uploaded_file is not None:
        st.session_state["uploaded_file"] = uploaded_file
    
    if "uploaded_file" in st.session_state:
        uploaded_file = st.session_state["uploaded_file"]
        xls = pd.ExcelFile(uploaded_file)
        sheet_name = st.selectbox("Select a sheet to process", xls.sheet_names, index=st.session_state.get("sheet_name_index", 0))
        skip_top_rows = st.number_input("Number of top rows to remove (headers, extra text, etc.)", min_value=0, value=st.session_state.get("skip_top_rows", 0))
        df = pd.read_excel(uploaded_file, sheet_name=sheet_name, skiprows=skip_top_rows)
        skip_bottom_rows = st.number_input("Number of bottom rows to remove (extra blank rows, totals, etc.)", min_value=0, value=st.session_state.get("skip_bottom_rows", 0))
        if skip_bottom_rows > 0:
            df = df.iloc[:-skip_bottom_rows]
        
        st.subheader("Preview of Data After Removing Unwanted Rows")
        st.write(df.head())
        st.write(df.tail())
        
        # Map VIN Column
        st.subheader("Map VIN Column")
        vin_column_options = ["(None)"] + list(df.columns)
        vin_column = st.selectbox("Select column for VIN", options=vin_column_options, index=st.session_state.get("vin_column_index", 0))
        
        if vin_column != "(None)":
            df["Cleaned VIN"] = df[vin_column].astype(str).apply(clean_vin)
            st.subheader("Original and Cleaned VINs")
            st.dataframe(df[[vin_column, "Cleaned VIN"]].head())
        
        # Desired column mappings
        desired_columns = [
            "State", "City", "Zip", "Garage Territory", "Vehicle Year",
            "Make", "Model", "Class Code", "GVW", "Cost New"
        ]
        st.subheader("Map Existing Columns to Desired Column Names")
        column_mapping = {}
        for col in desired_columns:
            column_mapping[col] = st.selectbox(f"Select column for '{col}'", options=vin_column_options, index=st.session_state.get(f"col_{col}_index", 0))
        
        # Create new dataframe with only selected columns
        selected_columns = {k: v for k, v in column_mapping.items() if v != "(None)"}
        if vin_column != "(None)":
            selected_columns["VIN"] = vin_column
            selected_columns["Cleaned VIN"] = "Cleaned VIN"

        # Extract data using selected columns but **rename them to desired names**
        final_df = pd.DataFrame()

        for desired_col, uploaded_col in selected_columns.items():
            final_df[desired_col] = df[uploaded_col]  # Use desired column names directly
        
        st.session_state["mapped_df"] = final_df
        st.subheader("Final Input Data")
        st.write(final_df)
        
        # Save Inputs Button
        if st.button("Save Inputs"):
            st.session_state["sheet_name_index"] = xls.sheet_names.index(sheet_name)
            st.session_state["skip_top_rows"] = skip_top_rows
            st.session_state["skip_bottom_rows"] = skip_bottom_rows
            st.session_state["vin_column_index"] = vin_column_options.index(vin_column)
            for col in desired_columns:
                st.session_state[f"col_{col}_index"] = vin_column_options.index(column_mapping.get(col, "(None)"))
            st.success("Inputs saved successfully!")

elif page == "VIN Processing & Results":
    st.subheader("Decode VINs using NHTSA API")
    if "mapped_df" in st.session_state:
        mapped_df = st.session_state["mapped_df"]
        if "Cleaned VIN" in mapped_df.columns:
            if st.button("Decode VINs"):
                decoded_vin_df = decode_vins(mapped_df["Cleaned VIN"].tolist())
                selected_fields = ["VIN", "Make", "Model", "VehicleType", "GVWR", "ModelYear" , "BodyClass"]
                decoded_vin_df = decoded_vin_df[selected_fields]
                
                # Compute class codes
                decoded_vin_df["GVW"] = decoded_vin_df["GVWR"].apply(extract_gvwr_weight)
                decoded_vin_df["Mapped Vehicle Type"] = decoded_vin_df.apply(lambda row: map_vehicle_type(row["VehicleType"], row["BodyClass"], row["GVW"]), axis=1)
                decoded_vin_df["Class Code"] = decoded_vin_df["Mapped Vehicle Type"].apply(map_class_code)
                
                st.session_state["decoded_vin_df"] = decoded_vin_df
                st.success("VINs decoded and class codes assigned successfully!")
    
    if "decoded_vin_df" in st.session_state:
        st.subheader("Decoded VIN Results with Class Codes")
        st.write(st.session_state["decoded_vin_df"])

    st.subheader("Business Type")
    business_type = st.radio("Select Business Type:", ["New Business", "Renewal Business"])
    st.session_state["business_type"] = business_type

    if "decoded_vin_df" in st.session_state and "mapped_df" in st.session_state:
        decoded_vin_df = st.session_state["decoded_vin_df"].copy()
        final_df = st.session_state["mapped_df"].copy()

        # Merge data: decoded_vin_df takes priority, but final_df fills missing values
        if not decoded_vin_df.empty:
            vehicle_schedule = decoded_vin_df.combine_first(final_df)
        else:
            vehicle_schedule = final_df

        # Ensure all required columns exist, filling missing ones with an empty string
        vehicle_schedule = vehicle_schedule.reindex(columns=vehicle_schedule_fields, fill_value="")

        st.subheader("Final Vehicle Schedule Data")
        st.write(vehicle_schedule)

        st.session_state["vehicle_schedule"] = vehicle_schedule

        if st.button("Download Vehicle Schedule as CSV"):
            csv = vehicle_schedule.to_csv(index=False).encode("utf-8")
            st.download_button("Download CSV", data=csv, file_name="vehicle_schedule.csv", mime="text/csv")

 

