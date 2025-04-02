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
    elif vehicle_type =="MULTIPURPOSE PASSENGER VEHICLE (MPV)" or vehicle_type == "PASSENGER CAR":
        return "PPT"
    elif body_class == "Truck-Tractor" and gvw <= 45000:
        return "Truck Tractor_H"
    elif body_class == "Truck-Tractor" and gvw > 45000:
        return "Truck Tractor_XH"
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
    


vehicle_type_code_mapping = {
    "739800": "1",
    "014890": "3",
    "214890": "3",
    "314890": "3",
    "404890": "3",
    "414890": "4",
    "504890": "4",
    "684890": "5"
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

def check_deductible_restrictions(df):
    violations = []
    warnings = []

    for idx, row in df.iterrows():
        try:
            cost_new = float(row.get("Cost New", 0))
            model = str(row.get("Model", "")).upper()
            class_code = str(row.get("Class Code", ""))
            otc_ded = float(row.get("OTC Deductible", 0))
            coll_ded = float(row.get("Collision Ded", 0))
        except:
            continue

        # Map Class Code to Vehicle Type
        vehicle_type = next((k for k, v in class_code_mapping.items() if v == class_code), "Unknown")

        # Rule 1: Trucks > $100k need $5k minimum deductible
        if vehicle_type in ["Light Truck", "Medium Truck", "Heavy Truck", "Extra Heavy Truck", "Truck Tractor_H", "Truck Tractor_XH"] and cost_new > 100000:
            if otc_ded < 5000 or coll_ded < 5000:
                violations.append({**row, "Reason": "Truck > $100k requires $5k minimum deductible"})

        # Rule 2: Cybertruck requires $10k minimum deductible
        if "CYBERTRUCK" in model:
            if otc_ded < 10000 or coll_ded < 10000:
                violations.append({**row, "Reason": "Cybertruck requires $10k minimum deductible"})

        # Rule 3: PPT > $125k needs $10k deductible
        if vehicle_type == "PPT" and cost_new > 125000:
            if otc_ded < 10000 or coll_ded < 10000:
                violations.append({**row, "Reason": "PPT > $125k requires $10k minimum deductible"})

    # Rule 4: Trucks > $200k referral warning
    referral_vehicles = df[
        (df["Cost New"] > 200000) &
        df["Class Code"].isin([class_code_mapping[k] for k in [
            "Light Truck", "Medium Truck", "Heavy Truck", "Extra Heavy Truck", "Truck Tractor_H", "Truck Tractor_XH"
        ]])
    ]
    if not referral_vehicles.empty:
        warnings.append("🚨 Referral to Chubb required for trucks over $200k.")

    return pd.DataFrame(violations), warnings

vehicle_schedule_fields = [
    "State", "Vehicle Sequence No", "City", "Zip", "Garage Territory", "Town Code",
    "County Code", "Tax Terr Code", "Vehicle Year", "Make", "Model", "VIN",
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
page = st.sidebar.radio("Go to:", ["Upload & Preprocessing", "VIN Processing" , "Coverage Processing"])

if page == "Upload & Preprocessing":
    st.markdown("## 📥 Upload & Preprocessing")
    st.markdown("Use this section to upload and clean your Excel data.")
    st.markdown("---")
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
        st.subheader("Map VIN Column, this is necessary for next steps")
        vin_column_options = ["(None)"] + list(df.columns)
        vin_column = st.selectbox("Select column for VIN", options=vin_column_options, index=st.session_state.get("vin_column_index", 0))
        
        if vin_column != "(None)":
            df["Cleaned VIN"] = df[vin_column].astype(str).apply(clean_vin)
            st.subheader("VINs below are corrected for O for 0, I for 1, and extra spaces")

            # Filter to show only changed VINs
            filtered_vin_df = df[df[vin_column] != df["Cleaned VIN"]][[vin_column, "Cleaned VIN"]]

            # Display only if there are modified VINs
            if not filtered_vin_df.empty:
                st.dataframe(filtered_vin_df)
            else:
                st.write("No VINs were modified during cleaning.")
        
        # Desired column mappings
        desired_columns = [
            "State", "City", "Zip", "Vehicle Year",
            "Make", "Model", "Class Code", "GVW", "Cost New"
        ]
        st.subheader("Map Other Columns From Submission")
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
            st.success("Inputs saved successfully! Please move on to VIN Processing step")

elif page == "VIN Processing":
    st.header("🔍 Step 1: Decode VINs with NHTSA API")
    st.markdown(
        "Use this section to decode VINs and retrieve vehicle data from the [NHTSA API](https://vpic.nhtsa.dot.gov/). "
        "Click the button below to start the decoding process."
    )

    if "mapped_df" in st.session_state:
        mapped_df = st.session_state["mapped_df"]
        if st.button("🔍 Decode VINs"):
            with st.spinner("Decoding VINs... this may take a moment."):
                start_time = time.time()
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
            st.write(st.session_state["decoded_vin_df"])  

            # Display the error table as an **interactive editable table**
            if not error_df.empty:
                st.subheader("⚠️ Invalid VINs – Manual Review Required")
                st.markdown(
                    "Some VINs couldn't be decoded. Please review and correct these values manually in the next section"
                )
                st.write(error_df)

                # # Initialize session state for corrected data if not already set
                # if "corrected_error_df" not in st.session_state:
                #     st.session_state["corrected_error_df"] = error_df.copy()

                # # Button to auto-fill missing values
                # if st.button("Fill Missing Make, Model, and Class Code with Trailer"):
                #     corrected_df = st.session_state["corrected_error_df"].copy()
                #     corrected_df.loc[corrected_df["Make"].isna() | (corrected_df["Make"] == ""), "Make"] = "Trailer"
                #     corrected_df.loc[corrected_df["Model"].isna() | (corrected_df["Model"] == ""), "Model"] = "Trailer"
                #     corrected_df.loc[corrected_df["Class Code"].isna() | (corrected_df["Class Code"] == "" ) | (corrected_df["Class Code"] == "Unknown" ), "Class Code"] = "684890"

                #     # Save changes to session state and force rerun
                #     st.session_state["corrected_error_df"] = corrected_df
                #     st.rerun()  # Forces Streamlit to refresh the UI with updated table

                # Editable Data Table (Without Class Code Restriction)
                # edited_error_df = st.data_editor(st.session_state["corrected_error_df"], num_rows="dynamic")

                # # Save corrected data
                # if st.button("Save Corrected VINs"):
                #     st.session_state["corrected_error_df"] = edited_error_df
                #     st.success("Corrections saved successfully!")
            else:
                st.write("No Invalid VINs")

        else:
            # If "ErrorCode" column does not exist, display full dataframe as default
            st.write(st.session_state["decoded_vin_df"])


        

 
    if "decoded_vin_df" in st.session_state and "mapped_df" in st.session_state:
        st.divider()
        st.header("📝 Step 2: Review and Modify Vehicle Information")
        st.markdown(
            "This section allows you to review the decoded vehicle data, update any incorrect or missing information, "
            "and ensure class codes are accurate before proceeding."
        )
        st.subheader("Mapped Vehicle List")
        if "corrected_vehicle_schedule" not in st.session_state:
            decoded_vin_df_cleaned = st.session_state["decoded_vin_df"].copy()[['Cleaned VIN', 'Make', 'Model', 'Vehicle Year', 'GVW', 'Class Code']]

            # Merge data: decoded_vin_df takes priority, final_df fills missing values
            vehicle_schedule = decoded_vin_df_cleaned.combine_first(st.session_state["mapped_df"].copy())
            vehicle_schedule.drop(['VIN'], axis=1, inplace=True)
            vehicle_schedule.rename(columns={'Cleaned VIN': 'VIN'}, inplace=True)
            st.session_state["corrected_vehicle_schedule"] = vehicle_schedule


        # Create a two-column layout to display the updated schedule and summary
        col1, col2 = st.columns([3,1])
        
        with col1:
            st.write(st.session_state["corrected_vehicle_schedule"])
        
        with col2:
            df = st.session_state["corrected_vehicle_schedule"]
            summary_df = df.groupby("Class Code").size().reset_index(name="Vehicle Count")

            # Calculate Power Units subtotal and total
            power_units_count = df[df["Class Code"] != "684890"].shape[0]
            total_count = df.shape[0]

            # Append Power Units and Total rows
            summary_df = pd.concat([
                summary_df,
                pd.DataFrame([{"Class Code": "Power Units", "Vehicle Count": power_units_count}]),
                pd.DataFrame([{"Class Code": "Total Units", "Vehicle Count": total_count}])
            ], ignore_index=True)

            # Format table with bold styling for subtotal and total
            def format_row(row):
                if row["Class Code"] in ["Power Units", "Total Units"]:
                    return f"<tr><td><b>{row['Class Code']}</b></td><td><b>{row['Vehicle Count']}</b></td></tr>"
                else:
                    return f"<tr><td>{row['Class Code']}</td><td>{row['Vehicle Count']}</td></tr>"

            table_rows = "\n".join(summary_df.apply(format_row, axis=1))

            html_table = f"""
            <h5 style='font-size:16px;'>Vehicle Count by Class Code</h5>
            <table style='width:100%; border-collapse: collapse;'>
                <thead>
                    <tr>
                        <th style='text-align: left;'>Class Code</th>
                        <th style='text-align: right;'>Vehicle Count</th>
                    </tr>
                </thead>
                <tbody>
                    {table_rows}
                </tbody>
            </table>
            """

            st.markdown(html_table, unsafe_allow_html=True)





        # Create a filter input for Class Code
        filter_value = st.text_input("Filter by Class Code and make changes:")

        # Filter the DataFrame based on the input value
        if filter_value:
            filtered_df = st.session_state["corrected_vehicle_schedule"][
                st.session_state["corrected_vehicle_schedule"]["Class Code"].str.contains(filter_value, case=False, na=False)
            ]
        else:
            filtered_df = st.session_state["corrected_vehicle_schedule"]

        # Display the filtered data in the editable table
        edited_vehicle_schedule = st.data_editor(filtered_df, num_rows="dynamic")

        if st.button("Save Changes"):
            # Get the edited DataFrame from the data editor
            edited_df = edited_vehicle_schedule.copy()
            
            # Get the full DataFrame from session state
            full_df = st.session_state["corrected_vehicle_schedule"]
            
            # Assume that "VIN" is unique and exists in both DataFrames.
            # Set the index to "VIN" for merging purposes
            full_df = full_df.set_index("VIN")
            edited_df = edited_df.set_index("VIN")
            
            # Update only the rows that were edited (present in the filtered view)
            full_df.update(edited_df)
            
            # Reset the index if needed
            st.session_state["corrected_vehicle_schedule"] = full_df.reset_index()
            
            st.success("Changes saved successfully!")

            st.rerun()

        st.header("After reviewing and finalizing vehicle info, please move on to Coverage Processing step")
        # st.write("After reviewing and finalizing vehicle info, please move on to Coverage Processing step")

elif page == "Coverage Processing":
    st.header("Coverage Processing and Underwriting Checks")

    if "corrected_vehicle_schedule" in st.session_state:
        df_coverage = st.session_state["corrected_vehicle_schedule"].copy()

        # Ensure deductible columns exist
        if "OTC Deductible" not in df_coverage.columns:
            df_coverage["OTC Deductible"] = ""
        if "Collision Ded" not in df_coverage.columns:
            df_coverage["Collision Ded"] = ""

        st.subheader("Underwriting Deductible Rules")

        # Rule 1: Power Units less than 10 years old require 5k deductible
        if st.button("Apply Rule 1: Power Units < 10 yrs → $5K Deductible"):
            current_year = pd.Timestamp.now().year
            vehicle_year_series = pd.to_numeric(df_coverage["Vehicle Year"], errors="coerce")
            
            condition = (
                (~df_coverage["Class Code"].isin(["684890"])) &  # Not trailer = power unit
                (vehicle_year_series >= current_year - 10)
            )
            df_coverage.loc[condition, ["OTC Deductible", "Collision Ded"]] = "5000"
            st.success(f"Rule 1 applied to {condition.sum()} vehicles.")

        if "Cost New" in df_coverage.columns:

            # Rule 2: Trucks over $100K require minimum $5k deductible
            if st.button("Apply Rule 2: Trucks > $100K → $5K Deductible"):
                cost_new = pd.to_numeric(df_coverage["Cost New"], errors="coerce")
                is_truck = ~df_coverage["Class Code"].isin(["739800", "684890"])
                condition = is_truck & (cost_new > 100000)

                df_coverage.loc[condition, ["OTC Deductible", "Collision Ded"]] = "5000"
                st.success(f"Rule 2 applied to {condition.sum()} vehicles.")


            # Rule 3: Cybertruck requires 10k ded
            if st.button("Apply Rule 3: Cybertruck → $10K Deductible"):
                condition = df_coverage["Model"].str.contains("CYBERTRUCK", case=False, na=False)
                df_coverage.loc[condition, ["OTC Deductible", "Collision Ded"]] = "10000"
                st.success(f"Rule 3 applied to {condition.sum()} vehicles.")

            # Rule 4: PPT over $125K → $10K Deductible
            if st.button("Apply Rule 4: PPTs > $125K → $10K Deductible"):
                condition = (
                    (df_coverage["Class Code"] == "739800") &
                    (df_coverage["Cost New"].astype(float) > 125000)
                )
                df_coverage.loc[condition, ["OTC Deductible", "Collision Ded"]] = "10000"
                st.success(f"Rule 4 applied to {condition.sum()} vehicles.")

            # Rule 5: Trucks over $200K → Referral Warning
            referral_condition = (
                (~df_coverage["Class Code"].isin(["739800", "684890"])) &  # Not PPT or trailer = truck
                (df_coverage["Cost New"].astype(float) > 200000)
            )
            if referral_condition.any():
                st.warning(f"Referral to Chubb: {referral_condition.sum()} Trucks(s) exceed $200K in Cost New.")

        else:
             st.write("Submission does not contain Cost New — cannot apply underwriting restrictions related to cost.")
        
        # Update session state
        st.session_state["corrected_vehicle_schedule"] = df_coverage

        st.divider()
        st.subheader("📌 Additional Adjustments")

        # Layout: two side-by-side input sections
        col1, col2 = st.columns(2)

        with col1:
            st.markdown("**Set Minimum Cost New for Trailers**")
            trailer_threshold = st.number_input(
                "Enter minimum Cost New for trailers",
                min_value=0.0,
                value=10000.0,
                step=1000.0,
                key="trailer_cost_threshold"
            )

            if st.button("Update Trailer Cost New"):
                # Ensure "Cost New" column exists
                if "Cost New" not in df_coverage.columns:
                    df_coverage["Cost New"] = 0.0  # or you can choose to set it as np.nan

                is_trailer = df_coverage["Class Code"] == "684890"
                cost_new_numeric = pd.to_numeric(df_coverage["Cost New"], errors="coerce").fillna(0.0)
                condition = is_trailer & (cost_new_numeric < trailer_threshold)

                df_coverage.loc[condition, "Cost New"] = trailer_threshold
                st.success(f"Updated {condition.sum()} trailer(s) to minimum ${int(trailer_threshold):,}.")


        # --- 2. Fill Missing Deductibles ---
        with col2:
            st.markdown("**Fill Missing Deductibles**")
            missing_ded_amount = st.number_input(
                "Enter deductible amount to apply to missing values",
                min_value=0.0,
                value=5000.0,
                step=500.0,
                key="fill_missing_deds"
            )

            if st.button("Fill Missing OTC & Collision Deductibles"):
                otc_missing = df_coverage["OTC Deductible"].isna() | (df_coverage["OTC Deductible"] == "")
                coll_missing = df_coverage["Collision Ded"].isna() | (df_coverage["Collision Ded"] == "")
                total_updates = otc_missing.sum() + coll_missing.sum()

                df_coverage.loc[otc_missing, "OTC Deductible"] = str(int(missing_ded_amount))
                df_coverage.loc[coll_missing, "Collision Ded"] = str(int(missing_ded_amount))

                st.success(f"Filled missing deductibles for {total_updates} field(s).")


        # Editable table
        st.subheader("Review and Adjust Deductibles")
        edited_df = st.data_editor(df_coverage, num_rows="dynamic")
        if st.button("Save Changes"):
            st.session_state["corrected_vehicle_schedule"] = edited_df
            st.success("Changes saved successfully!")

        st.subheader("Batch Update: Coverage Fields")

        with st.form("batch_update_form"):
            # pip_value = st.selectbox("Set PIP for all vehicles", ["", "Y", "N"])
            # addtl_pip_value = st.selectbox("Set Addt'l PIP for all vehicles", ["", "Y", "N"])
            medpay_value = st.selectbox("Set Med Pay for all units", ["", "Y", "N"])
            um_uim_value = st.selectbox("Set UM UIM for all power units", ["", "Y", "N"])
            um_pd_value = st.selectbox("Set UM PD for all units", ["", "Y", "N"])
            acv_stated_value = st.selectbox("Set ACV or Stated Amount (A/S) for all units", ["", "A", "S"])
            towing_value = st.selectbox("Set Towing for PPT", ["", "Y", "N"])

            submitted = st.form_submit_button("Apply Values")

        if submitted:
            # Initialize the columns if they don't exist
            for col in [ "Med Pay", "UM UIM", "UM PD", "ACV or Stated Amount", "Towing"]:
            # for col in ["PIP", "Addt'l PIP", "Med Pay", "UM UIM", "UM PD", "ACV or Stated Amount", "Towing"]:
                if col not in df_coverage.columns:
                    df_coverage[col] = ""

            # if pip_value:
            #     df_coverage["PIP"] = pip_value
            # if addtl_pip_value:
            #     df_coverage["Addt'l PIP"] = addtl_pip_value
            if medpay_value:
                df_coverage["Med Pay"] = medpay_value
            if um_uim_value:
                non_trailer_mask = df_coverage["Class Code"] != "684890"
                df_coverage.loc[non_trailer_mask, "UM UIM"] = um_uim_value
            if um_pd_value:
                # non_trailer_mask = df_coverage["Class Code"] != "684890"
                # df_coverage.loc[non_trailer_mask, "UM PD"] = um_pd_value
                df_coverage["UM PD"] = um_pd_value
            if acv_stated_value:
                df_coverage["ACV or Stated Amount"] = acv_stated_value
            if towing_value:
                ppt_mask = df_coverage["Class Code"] == "739800"
                df_coverage.loc[ppt_mask, "Towing"] = towing_value


            
            st.session_state["corrected_vehicle_schedule"] = df_coverage

            st.success("Batch coverage values applied successfully!")
            st.write(st.session_state["corrected_vehicle_schedule"])

        
        df_final = df_coverage.reindex(columns=vehicle_schedule_fields, fill_value="")
        df_final["Vehicle Sequence No"] = df_final.index + 1        
        df_final = df_final.reset_index(drop=True)

        # getting vehicle type code
        df_final["Vehicle Type Code"] = df_final["Class Code"].map(vehicle_type_code_mapping).fillna("")


        # CompGroup set to 1
        df_final["CompGroupNo"] = 1

        #Mis Collision
        df_final["Misc Collision"] = "N"


        # OTC Coverage logic
        df_final["OTC Coverage"] = df_final["OTC Deductible"].apply(lambda x: "0" if pd.notna(x) and str(x).strip() != "" else "")

        # Collision Coverage logic
        df_final["Collision Coverage"] = df_final["Collision Ded"].apply(lambda x: "Y" if pd.notna(x) and str(x).strip() != "" else "N")

        ppt_mask = df_final["Class Code"] == "739800"
        df_final.loc[ppt_mask, "Rental Reimbursement Cov"] = "1,3"
        df_final.loc[ppt_mask, "Rental Reimbursement Max Amt"] = 50
        df_final.loc[ppt_mask, "Rental Reimbursement Max Days #"] = 30

        st.session_state["final_vehicle_schedule"] = df_final

        st.write("Final Vehicle Schedule")
        st.write(st.session_state["final_vehicle_schedule"])




        # st.subheader("test")
    # if "vehicle_schedule" in st.session_state:
    #     vehicle_schedule = st.session_state["vehicle_schedule"]
    #     # Ensure required columns exist before creating summary
    #     if "State" in vehicle_schedule.columns and "Class Code"  in vehicle_schedule.columns:
            
    #         # Aggregate counts by State and Class Code
    #         summary_df = vehicle_schedule.groupby(["State","Class Code"]).size().reset_index(name="Vehicle Count")
            
    #         # Display summary data
    #         st.subheader("Summary: Number of Vehicles by State Vehicle Type")
    #         st.dataframe(summary_df)
    #     Ensure all required columns exist and fill missing ones with empty strings
    #     vehicle_schedule = vehicle_schedule.reindex(columns=vehicle_schedule_fields, fill_value="")