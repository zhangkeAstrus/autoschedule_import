import streamlit as st
import pandas as pd
import requests
import re  # Import regex for extracting GVWR numbers
# import win32com.client  # Requires pywin32
import pythoncom  # Needed for COM initialization in Streamlit
import time

# VIN Cleaning Function
def clean_vin(vin):
    """Cleans up the VIN by trimming spaces and replacing O->0, I->1."""
    if pd.isna(vin):  # Handle missing values
        return vin
    return vin.strip().upper().replace("O", "0").replace("I", "1")

# Function to decode VINs using NHTSA API
def decode_vins(vins):
    url = "https://vpic.nhtsa.dot.gov/api/vehicles/DecodeVINValuesBatch/"
    batch_size = 50  # NHTSA API limit

    all_results = []  # List to store all decoded results

    # Process in batches of 50
    for i in range(0, len(vins), batch_size):
        batch = vins[i : i + batch_size]  # Get the current batch

        params = {"format": "json", "data": ";".join(batch)}
        response = requests.post(url, data=params)

        if response.status_code == 200:
            results = response.json().get("Results", [])
            all_results.extend(results)  # Append results to list
        else:
            st.error(f"Error fetching VIN data from NHTSA API for batch {i // batch_size + 1}")

    # Convert results to DataFrame
    return pd.DataFrame(all_results) if all_results else pd.DataFrame()


# Function to extract weight (GVWR) from text
def extract_gvwr_weight(gvwr_text):
    """Extracts the first numeric weight value in pounds from GVWR text."""
    if pd.isna(gvwr_text) or gvwr_text.strip() == "":
        return None
    match = re.search(r"(\d{1,3}(?:,\d{3})*)\s*lb", gvwr_text)  # Extracts first number in lbs
    if match:
        return int(match.group(1).replace(",", ""))  # Convert to integer
    return None

# Function to determine Vehicle Type based on GVWR and VehicleType
def map_vehicle_type(vehicle_type, gvwr_text):
    """Maps GVWR and VehicleType to the corresponding Vehicle Type category."""
    if vehicle_type == "TRAILER":
        return "Trailer"
    elif vehicle_type == "INCOMPLETE VEHICLE":
        return "Truck Tractor"
    
    gvwr = extract_gvwr_weight(gvwr_text)
    if gvwr is None:
        return "Unknown"

    if gvwr <= 10000:
        return "Light Truck"
    elif gvwr <= 20000:
        return "Medium Truck"
    elif gvwr <= 45000:
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

st.title("Vehicle Schedule Submission Review")

# Sidebar Navigation
st.sidebar.title("Navigation")
page = st.sidebar.radio("Go to:", ["Upload & Preprocessing", "VIN Processing & Results"])

# Step 1: Upload the Excel File (Present in both tabs)
uploaded_file = st.file_uploader("Upload an Excel file with vehicle submission data", type=["xlsx"])

if uploaded_file is not None:
    xls = pd.ExcelFile(uploaded_file)
    sheet_name = st.selectbox("Select a sheet to process", xls.sheet_names)

    # Input for number of rows to skip at the top
    skip_top_rows = st.number_input("Number of top rows to remove (headers, extra text, etc.)", min_value=0, value=0)

    # Read the selected sheet, skipping top rows
    df = pd.read_excel(uploaded_file, sheet_name=sheet_name, skiprows=skip_top_rows)

    # Input for number of rows to remove from the bottom
    skip_bottom_rows = st.number_input("Number of bottom rows to remove (extra blank rows, totals, etc.)", min_value=0, value=0)

    # Remove bottom rows if specified
    if skip_bottom_rows > 0:
        df = df.iloc[:-skip_bottom_rows]

    if page == "Upload & Preprocessing":
        st.subheader("Preview of Data After Removing Unwanted Rows")
        st.write(df.head())
        st.write(df.tail())

        # Desired column mappings
        desired_columns = [
            "State", "City", "Zip", "Garage Territory", "Vehicle Year",
            "Make", "Model", "Class Code", "GVW", "Cost New"
        ]

        # Column mapping step
        st.subheader("Map Existing Columns to Desired Column Names")
        column_mapping = {}
        for col in desired_columns:
            column_mapping[col] = st.selectbox(f"Select column for '{col}'", options=["(None)"] + list(df.columns), index=0)

        # Apply column mapping
        mapped_df = df.rename(columns={v: k for k, v in column_mapping.items() if v != "(None)"})



        # Store mapped_df and vin_column in session state
        st.session_state["mapped_df"] = mapped_df
        

    elif page == "VIN Processing & Results":

        # Business Type Selection
        business_type = st.radio("Select Business Type:", ["New Business", "Renewal Business"])

        # Store the business type in session state
        st.session_state["business_type"] = business_type

        # if business_type == "Renewal Business":
        #     # renewal_xml = st.file_uploader("Upload the XML file for Renewal Business", type=["xml"])
            
        #     # if renewal_xml is None:
        #     #     st.warning("Please upload an XML file to proceed with Renewal Business.")
        #     #     st.stop()  # Stop further execution if XML file is not uploaded

        #     # Define the full path to the macro-enabled workbook
        #     macro_workbook_path = r"C:\Users\ez4ke.KDAWG\Desktop\astrus\autoschedule_import\Auto Schedule XML Import Export.xlsm"
        #     # macro_workbook_path = r"C:\Users\kzhang2\scripts\auto import\Auto Schedule XML Import Export.xlsm"

        #     # Run the macro using Excel COM interface
        #     try:
        #         pythoncom.CoInitialize()  # Fix for CoInitialize error
                
        #         excel = win32com.client.Dispatch("Excel.Application")
        #         excel.Visible = True  # Run in the background

        #         wb = excel.Workbooks.Open(macro_workbook_path)
                
        #         # Run the macro to process the XML file
        #         excel.Application.Run("'Auto Schedule XML Import Export.xlsm'!ThisWorkbook.ImportXML")
                
        #         # Allow time for macro execution
        #         time.sleep(2)  # Adjust this time if needed
                
        #         # Get the processed data from the "Vehicle Schedule" tab
        #         ws = wb.Sheets("Vehicle Schedule")
                
        #         # Set explicit column range (B:AQ corresponds to columns 2:43 in Excel)
        #         start_col = 2  # Column B
        #         end_col = 43   # Column AQ

        #         # Find the last used row based on column B (ensuring we capture all data)
        #         last_row = ws.Cells(ws.Rows.Count, start_col).End(-4162).Row  # -4162 is xlUp

        #         # Read column headers (row 6)
        #         headers = [ws.Cells(6, col).Value for col in range(start_col, end_col + 1)]

        #         # Read data from row 7 onwards
        #         data = []
        #         for row in range(7, last_row + 1):  # Start from row 7
        #             row_data = [ws.Cells(row, col).Value for col in range(start_col, end_col + 1)]
                    
        #             # Ensure we're not adding empty rows (skip completely blank rows)
        #             if any(row_data):  # If any value in row is non-empty, add to data
        #                 data.append(row_data)

        #         # Convert to DataFrame
        #         vehicle_schedule_df = pd.DataFrame(data, columns=headers)

        #         # Close the workbook (without saving)
        #         wb.Close(SaveChanges=False)
        #         excel.Quit()

        #         # Properly release COM object (prevent memory leaks)
        #         del excel
                

        #         # Display the extracted data
        #         st.subheader("Processed Vehicle Schedule (from Excel Macro)")
        #         st.write(vehicle_schedule_df)

        #         # Provide a download option
        #         csv = vehicle_schedule_df.to_csv(index=False).encode("utf-8")
        #         st.download_button("Download Vehicle Schedule Data", csv, "vehicle_schedule.csv", "text/csv")

        #     except Exception as e:
        #         st.error(f"Error running the macro or reading the Excel file: {e}")

        #     finally:
        #         pythoncom.CoUninitialize()  # Proper cleanup        


        # Select VIN Column
        vin_column = st.selectbox("Select the VIN column", options=["(None)"] + list(df.columns), index=0)
        st.session_state["vin_column"] = vin_column

        if "mapped_df" in st.session_state and "vin_column" in st.session_state:
            mapped_df = st.session_state["mapped_df"]
            vin_column = st.session_state["vin_column"]

            if vin_column != "(None)":
                # Clean VINs
                mapped_df["Cleaned VIN"] = df[vin_column].astype(str).apply(clean_vin)

                # Identify changed VINs
                mapped_df["VIN Modified?"] = mapped_df.apply(lambda row: row[vin_column] != row["Cleaned VIN"], axis=1)

                # Decode VINs using NHTSA API
                st.subheader("Decoding VINs with NHTSA API")
                unique_vins = mapped_df["Cleaned VIN"].dropna().unique().tolist()

                if len(unique_vins) > 0:
                    vin_decoded_df = decode_vins(unique_vins)
                    
                    # Select only the desired fields
                    selected_fields = ["VIN", "Make", "Model", "VehicleType", "GVWR", "ModelYear"]
                    if not vin_decoded_df.empty:
                        vin_decoded_df = vin_decoded_df[selected_fields]

                        # Map Vehicle Type based on GVWR and VehicleType
                        vin_decoded_df["Vehicle Type"] = vin_decoded_df.apply(
                            lambda row: map_vehicle_type(row["VehicleType"], row["GVWR"]), axis=1
                        )

                        # Map Class Code based on Vehicle Type
                        vin_decoded_df["Class Code"] = vin_decoded_df["Vehicle Type"].apply(map_class_code)

                        vin_decoded_df.rename(columns={"ModelYear": "Vehicle Year"}, inplace=True)

                        # Merge decoded results back into the original dataframe
                        mapped_df = mapped_df.merge(vin_decoded_df, left_on="Cleaned VIN", right_on="VIN", how="left", suffixes=("_raw", "_nhtsa"))

                        # Create tabs for display
                        tab1, tab2 = st.tabs(["Processed Data", "Full VIN API Results"])

                        with tab1:
                            st.subheader("Processed Data (Cleaned VIN + Decoded Info)")
                            st.write(mapped_df.head())
                            csv = mapped_df.to_csv(index=False).encode('utf-8')
                            st.download_button("Download Processed Data", csv, "processed_vehicle_data.csv", "text/csv")

                        with tab2:
                            st.subheader("Full VIN Decoding Results")
                            st.write(vin_decoded_df)
                        
                        # Define Vehicle Schedule Import fields
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

                        # Prepare the Vehicle Schedule Import DataFrame
                        vehicle_schedule = pd.DataFrame()

                        for field in vehicle_schedule_fields:
                            # Check if the exact field exists
                            if field in mapped_df.columns:
                                vehicle_schedule[field] = mapped_df[field]

                            # Check if both _raw and _nhtsa versions exist
                            elif f"{field}_raw" in mapped_df.columns and f"{field}_nhtsa" in mapped_df.columns:
                                vehicle_schedule[field] = mapped_df.apply(
                                    lambda row: row[f"{field}_nhtsa"] if pd.notna(row[f"{field}_nhtsa"]) and row[f"{field}_nhtsa"] != "" 
                                    else row[f"{field}_raw"], axis=1
                                )

                            # Check if only _raw version exists
                            elif f"{field}_raw" in mapped_df.columns:
                                vehicle_schedule[field] = mapped_df[f"{field}_raw"]

                            # Check if only _nhtsa version exists
                            elif f"{field}_nhtsa" in mapped_df.columns:
                                vehicle_schedule[field] = mapped_df[f"{field}_nhtsa"]

                            # If no matching column, create an empty column
                            else:
                                vehicle_schedule[field] = ""

                        # Display the final Vehicle Schedule Import table
                        st.subheader("Vehicle Schedule Import Output")
                        st.write(vehicle_schedule)

                        # Download option for Vehicle Schedule Import
                        csv = vehicle_schedule.to_csv(index=False).encode('utf-8')
                        st.download_button("Download Vehicle Schedule Import", csv, "vehicle_schedule_import.csv", "text/csv")
                
        else:
            st.warning("Please complete the Upload & Preprocessing step first.")
