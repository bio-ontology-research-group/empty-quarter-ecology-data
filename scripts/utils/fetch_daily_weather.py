import pandas as pd
import requests
import os
import glob
import time
from datetime import datetime

# Config
GEO_DIR = "data/metadata/geodata"
OUTPUT_FILE = "data/processed/climate/daily_weather.tsv"
# Frozen window of the archived release. This was previously datetime.now(),
# which made the acquisition unreproducible: a later run silently covered a
# longer period and changed every derived count. The end date is the last date
# present in the archived table. Override with EQ_WEATHER_END_DATE only when
# deliberately extending the series, and record a new provenance entry.
START_DATE = os.environ.get("EQ_WEATHER_START_DATE", "2022-01-01")
END_DATE = os.environ.get("EQ_WEATHER_END_DATE", "2026-02-01")
API_URL = "https://archive-api.open-meteo.com/v1/archive"


def load_sites():
    files = glob.glob(os.path.join(GEO_DIR, "trip*_geodata.tsv"))
    all_sites = []
    for f in files:
        df = pd.read_csv(f, sep="\t")
        if (
            "Site" in df.columns
            and "Latitude" in df.columns
            and "Longitude" in df.columns
        ):
            # Ensure Site is string
            df["Site"] = df["Site"].astype(str)
            all_sites.append(df[["Site", "Latitude", "Longitude"]])

    combined = pd.concat(all_sites)
    sites = combined.groupby("Site").mean().reset_index()
    return sites


def load_existing_data():
    if os.path.exists(OUTPUT_FILE):
        print(f"Loading existing data from {OUTPUT_FILE}...")
        df = pd.read_csv(OUTPUT_FILE, sep="\t")
        df["Site"] = df["Site"].astype(str)
        return df
    return pd.DataFrame()


def fetch_weather(lat, lon, start, end):
    params = {
        "latitude": lat,
        "longitude": lon,
        "start_date": start,
        "end_date": end,
        "daily": ["temperature_2m_mean", "rain_sum", "precipitation_sum"],
        "timezone": "auto",
    }

    max_retries = 5
    for attempt in range(max_retries):
        try:
            response = requests.get(API_URL, params=params)

            if response.status_code == 429:
                print(f"  Rate limited (429). Waiting 65s...")
                time.sleep(65)
                continue

            response.raise_for_status()
            data = response.json()

            daily = data.get("daily", {})
            df = pd.DataFrame(daily)
            return df

        except Exception as e:
            print(f"  Error fetching {lat}, {lon}: {e}")
            if attempt < max_retries - 1:
                time.sleep(5)
            else:
                return None
    return None


def main():
    sites = load_sites()
    print(f"Total target sites: {len(sites)}")

    existing_df = load_existing_data()
    processed_sites = (
        set(existing_df["Site"].unique()) if not existing_df.empty else set()
    )
    print(f"Already processed: {len(processed_sites)}")

    # Filter sites
    sites_to_fetch = sites[~sites["Site"].isin(processed_sites)]
    print(f"Remaining to fetch: {len(sites_to_fetch)}")

    if sites_to_fetch.empty:
        print("All sites fetched.")
        return

    new_weather = []

    for _, row in sites_to_fetch.iterrows():
        site_id = str(row["Site"])
        lat = row["Latitude"]
        lon = row["Longitude"]

        print(f"Fetching Site {site_id} ({lat:.4f}, {lon:.4f})...")
        df = fetch_weather(lat, lon, START_DATE, END_DATE)

        if df is not None:
            df["Site"] = site_id
            df = df.rename(
                columns={
                    "time": "Date",
                    "temperature_2m_mean": "Mean_Temp_C",
                    "rain_sum": "Rain_mm",
                    "precipitation_sum": "Precip_mm",
                }
            )
            new_weather.append(df)

            # Save incrementally? Or just batch at end.
            # Append to file logic or concat logic.
            # Let's collect list and concat at end for safety/simplicity

        time.sleep(2.5)  # Conservative sleep

    if new_weather:
        new_df = pd.concat(new_weather)
        # Reorder cols
        cols = ["Site", "Date", "Mean_Temp_C", "Rain_mm", "Precip_mm"]
        new_df = new_df[cols]

        # Merge with existing
        final_df = pd.concat([existing_df, new_df]) if not existing_df.empty else new_df

        # Save
        final_df.to_csv(OUTPUT_FILE, sep="\t", index=False)
        print(f"Updated {OUTPUT_FILE} with {len(new_weather)} new sites.")
    else:
        print("No new data fetched successfully.")


if __name__ == "__main__":
    main()
