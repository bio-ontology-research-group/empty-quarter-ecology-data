import glob
import csv
import os


def parse_coordinates(coord_str):
    if not coord_str:
        return "-"
    # Format: "19.149770555555556 N,45.166511388888885 E"
    try:
        parts = coord_str.split(",")
        if len(parts) < 2:
            return coord_str
        lat = parts[0].strip()
        lon = parts[1].strip()
        # Let's clean it to 4 decimal places
        lat_val = float(lat.split()[0])
        lon_val = float(lon.split()[0])
        return f"{lat_val:.4f} N, {lon_val:.4f} E"
    except:
        return coord_str


def generate_table():
    # Source metadata is vendored in this repo under data/metadata/
    # (script lives in scripts/, so data/ is one level up).
    input_path = os.path.abspath(
        os.path.join(
            os.path.dirname(__file__), "../data/metadata/samplesheets/trip*-*.tsv"
        )
    )
    files = sorted(glob.glob(input_path))

    if not files:
        print(f"No files found at {input_path}")
        return

    output_rows = []

    for f in files:
        trip_name = os.path.basename(f).replace(".tsv", "").replace("-", " ").title()

        with open(f, "r") as tsvfile:
            # Read header first
            header_line = tsvfile.readline()
            if not header_line:
                continue

            fieldnames = header_line.strip().split("\t")
            # normalize
            fieldnames = [x.lower() for x in fieldnames]

            reader = csv.DictReader(tsvfile, fieldnames=fieldnames, delimiter="\t")

            for row in reader:
                site = row.get("site", "")
                date = row.get("date", "")
                time = row.get("time", "-")
                if not time:
                    time = "-"

                coords = parse_coordinates(row.get("coordinates", ""))
                temp = row.get("temperature", "-")
                pressure = row.get("pressure", "-")
                humidity = row.get("humidity", "-")

                # Handle empty strings or None
                if not pressure:
                    pressure = "-"
                if not temp:
                    temp = "-"
                if not humidity:
                    humidity = "-"

                output_rows.append(
                    [trip_name, site, date, time, coords, temp, pressure, humidity]
                )

    # Generate LaTeX
    latex_lines = []
    # Use smaller font
    latex_lines.append(r"\begin{scriptsize}")
    latex_lines.append(r"\begin{longtable}{llllllll}")
    latex_lines.append(
        r"\caption{Site-specific environmental measurements across all expeditions. Altitude data was not available.} \label{tab:env_data} \\"
    )
    latex_lines.append(r"\toprule")
    latex_lines.append(
        r"Expedition & Site & Date & Time & Coordinates & Temp (\degree C) & Press. (mbar) & Hum. (\%) \\"
    )
    latex_lines.append(r"\midrule")
    latex_lines.append(r"\endfirsthead")
    latex_lines.append(r"\toprule")
    latex_lines.append(
        r"Expedition & Site & Date & Time & Coordinates & Temp (\degree C) & Press. (mbar) & Hum. (\%) \\"
    )
    latex_lines.append(r"\midrule")
    latex_lines.append(r"\endhead")
    latex_lines.append(r"\midrule")
    latex_lines.append(r"\multicolumn{8}{r}{Continued on next page} \\")
    latex_lines.append(r"\bottomrule")
    latex_lines.append(r"\endfoot")
    latex_lines.append(r"\bottomrule")
    latex_lines.append(r"\endlastfoot")

    # Truncate to first 10 rows for the main article
    # if len(output_rows) > 10:
    #     output_rows = output_rows[:10]
    #     output_rows.append(["...", "...", "...", "...", "...", "...", "...", "..."])

    for row in output_rows:
        # Escape special chars if any (mostly fine here)
        clean_row = [str(x).replace("%", r"\%") for x in row]
        latex_lines.append(" & ".join(clean_row) + r" \\")

    latex_lines.append(r"\end{longtable}")
    latex_lines.append(r"\end{scriptsize}")

    output_file = os.path.join(os.path.dirname(__file__), "../paper/env_table.tex")
    with open(output_file, "w") as f:
        f.write("\n".join(latex_lines))
    print(f"Generated {output_file}")


if __name__ == "__main__":
    generate_table()
