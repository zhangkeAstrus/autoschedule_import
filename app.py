import streamlit as st
import pandas as pd
import requests
import re  # regex for extracting GVWR numbers
import time
import xml.etree.ElementTree as ET
import io
import matplotlib.pyplot as plt

st.set_page_config(layout="wide")

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
    elif vehicle_type =="MULTIPURPOSE PASSENGER VEHICLE (MPV)":
        return "PPT"
    elif body_class == "Truck-Tractor" and gvw <= 45000:
        return "Truck Tractor_H"
    elif body_class == "Truck-Tractor" and gvw > 45000:
        return "Truck Tractor_EH"
    elif gvw <= 10000:
        return "Light Truck"
    elif gvw <= 20000:
        return "Medium Truck"
    elif gvw <= 45000:
        return "Heavy Truck"
    elif gvw > 45000:
        return "Extra Heavy Truck"
    else:
        return "Unknown"
    
class_code_mapping = {
    "PPT": "739800",
    "Light Truck": "014890",
    "Medium Truck": "214890",
    "Heavy Truck": "314890",
    "Extra Heavy Truck": "414890",
    "Truck Tractor_H": "404890",
    "Truck Tractor_XH": "504890",
    "Trailer": "684890"
}


# Function to map Vehicle Type to Class Code
def map_class_code(vehicle_type):
    """Maps Vehicle Type to its respective Class Code."""
    class_code_mapping = {
        "PPT": "739800",
        "Light Truck": "014890",
        "Medium Truck": "214890",
        "Heavy Truck": "314890",
        "Extra Heavy Truck": "414890",
        "Truck Tractor_H": "404890",
        "Truck Tractor_XH": "504890",
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
            st.subheader("Original and Cleaned VINs (Only Modified VINs)")

            # Filter to show only changed VINs
            filtered_vin_df = df[df[vin_column] != df["Cleaned VIN"]][[vin_column, "Cleaned VIN"]]

            # Display only if there are modified VINs
            if not filtered_vin_df.empty:
                st.dataframe(filtered_vin_df)
            else:
                st.write("No VINs were modified during cleaning.")
        
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

        expected_dtypes = {
            "Vehicle Year": int,
            "GVW": float,
            "Cost New": float,
            "Zip": str  # Keep as str to preserve leading zeros
        }

        # Create new dataframe with mapped columns
        final_df = pd.DataFrame()
        for desired_col, uploaded_col in selected_columns.items():
            final_df[desired_col] = df[uploaded_col]

        # Convert data types and handle errors
        for col, dtype in expected_dtypes.items():
            if col in final_df.columns:
                try:
                    if dtype == int and col != "Zip":  # ZIP is handled separately
                        final_df[col] = pd.to_numeric(final_df[col], errors="coerce").fillna(0).astype(int)
                    elif dtype == float:
                        final_df[col] = pd.to_numeric(final_df[col], errors="coerce").fillna(0.0).astype(float)
                    elif col == "Zip":
                        # Convert to integer first, then back to string, then ensure 5-digit format
                        final_df[col] = pd.to_numeric(final_df[col], errors="coerce").fillna(0).astype(int).astype(str)
                        final_df[col] = final_df[col].apply(lambda x: x.zfill(5))  # Ensures leading zeros
                except Exception as e:
                    st.warning(f"Could not convert column {col} to {dtype}. Error: {str(e)}")

        # class codes adjustment
        if "Class Code" in final_df.columns:
            final_df["Class Code"] = pd.to_numeric(final_df["Class Code"], errors="coerce").fillna(0).astype(int)  # Ensure integer
            final_df["Class Code"] = final_df["Class Code"].astype(str).apply(lambda x: x.zfill(5) + "0")  # Format properly

        st.subheader("Final Input Data with Validated Data Types")
        st.write(final_df)
        st.session_state["mapped_df"] = final_df 
                
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
                start_time = time.time() # start timer

                decoded_vin_df = decode_vins(mapped_df["Cleaned VIN"].tolist())
                selected_fields = ["VIN", "Make", "Model", "VehicleType", "GVWR", "ModelYear" , "BodyClass", "ErrorCode", "ErrorText"]
                decoded_vin_df = decoded_vin_df[selected_fields]
                
                # Compute class codes
                decoded_vin_df["GVW"] = decoded_vin_df["GVWR"].apply(extract_gvwr_weight)
                decoded_vin_df["Mapped Vehicle Type"] = decoded_vin_df.apply(lambda row: map_vehicle_type(row["VehicleType"], row["BodyClass"], row["GVW"]), axis=1)
                decoded_vin_df["Class Code"] = decoded_vin_df["Mapped Vehicle Type"].apply(map_class_code)

                # Replace empty strings ("") with NaN to ensure combine_first() works correctly
                decoded_vin_df.replace("", pd.NA, inplace=True)

                decoded_vin_df.rename(columns = {"ModelYear" : "Vehicle Year", "VIN" : "Cleaned VIN"}, inplace = True)

                end_time = time.time() #End timer
                time_taken = round(end_time - start_time, 2) 

                num_vins_processed = len(decoded_vin_df)
                
                st.session_state["decoded_vin_df"] = decoded_vin_df
                st.success(f"Processed {num_vins_processed} vehicles. VINs decoded successfully in {time_taken} seconds!")
    
    if "decoded_vin_df" in st.session_state:
        st.subheader("Decoded VIN Results with Class Codes")
        
        # Check if 'ErrorCode' column exists
        if "ErrorCode" in st.session_state["decoded_vin_df"].columns:
            # Identify rows containing Error Codes 6 or 7
            error_df = st.session_state["decoded_vin_df"][
                st.session_state["decoded_vin_df"]["ErrorCode"]
                .astype(str)  # Convert to string
                .str.contains(r"\b6\b|\b7\b", regex=True, na=False)  # Match standalone 6 or 7
            ][['Cleaned VIN', 'Vehicle Year', 'Make', 'Model', 'Class Code', 'ErrorText']]

            # Exclude error rows from the main displayed dataframe
            valid_df = st.session_state["decoded_vin_df"].drop(error_df.index)

            # Display the valid VIN results
            st.write(valid_df)  

            # Display the error table as an **interactive editable table**
            if not error_df.empty:
                st.subheader("Invalid VINs, please fill them out")

                # Initialize session state for corrected data if not already set
                if "corrected_error_df" not in st.session_state:
                    st.session_state["corrected_error_df"] = error_df.copy()

                # Button to auto-fill missing values
                if st.button("Fill Missing Make, Model, and Class Code with Trailer"):
                    corrected_df = st.session_state["corrected_error_df"].copy()
                    corrected_df.loc[corrected_df["Make"].isna() | (corrected_df["Make"] == ""), "Make"] = "Trailer"
                    corrected_df.loc[corrected_df["Model"].isna() | (corrected_df["Model"] == ""), "Model"] = "Trailer"
                    corrected_df.loc[corrected_df["Class Code"].isna() | (corrected_df["Class Code"] == "" ) | (corrected_df["Class Code"] == "Unknown" ), "Class Code"] = "684890"

                    # Save changes to session state and force rerun
                    st.session_state["corrected_error_df"] = corrected_df
                    st.rerun()  # Forces Streamlit to refresh the UI with updated table

                # Editable Data Table (Without Class Code Restriction)
                edited_error_df = st.data_editor(st.session_state["corrected_error_df"], num_rows="dynamic")

                # Save corrected data
                if st.button("Save Corrected VINs"):
                    st.session_state["corrected_error_df"] = edited_error_df
                    st.success("Corrections saved successfully!")
            else:
                st.write("No Invalid VINs")

        else:
            # If "ErrorCode" column does not exist, display full dataframe as default
            st.write(st.session_state["decoded_vin_df"])


        

 
    # if "decoded_vin_df" in st.session_state and "mapped_df" in st.session_state:
    #     decoded_vin_df = st.session_state["decoded_vin_df"].copy()

    #     # Merge data: decoded_vin_df takes priority, final_df fills missing values
    #     vehicle_schedule = decoded_vin_df.combine_first(st.session_state["mapped_df"].copy())

    #     # Ensure all required columns exist and fill missing ones with empty strings
    #     vehicle_schedule = vehicle_schedule.reindex(columns=vehicle_schedule_fields, fill_value="")

    #     # st.write(decoded_vin_df[decoded_vin_df['Make']==''])
    #     # Save to session state for further processing
    #     st.session_state["vehicle_schedule"] = vehicle_schedule

    #     st.subheader("Final Vehicle Schedule Data")
    #     edited_vehicle_schedule = st.data_editor(vehicle_schedule, num_rows="dynamic")

    #     # Optionally save the edited DataFrame back to session state
    #     st.session_state["vehicle_schedule"] = edited_vehicle_schedule



    #     if st.button("Download Vehicle Schedule as CSV"):
    #         csv = vehicle_schedule.to_csv(index=False).encode("utf-8")
    #         st.download_button("Download CSV", data=csv, file_name="vehicle_schedule.csv", mime="text/csv")

    # if "vehicle_schedule" in st.session_state:
    #     vehicle_schedule = st.session_state["vehicle_schedule"]
    #     # Ensure required columns exist before creating summary
    #     if "State" in vehicle_schedule.columns and "Class Code"  in vehicle_schedule.columns:
            
    #         # Aggregate counts by State and Class Code
    #         summary_df = vehicle_schedule.groupby(["State","Class Code"]).size().reset_index(name="Vehicle Count")
            
    #         # Display summary data
    #         st.subheader("Summary: Number of Vehicles by State Vehicle Type")
    #         st.dataframe(summary_df)
