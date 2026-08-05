import os
import glob
import re
import csv
import sys

# Define input and output directories
INPUT_DIR = 'data/metadata/xrf/trip-5-lab/'
OUTPUT_DIR = 'data/processed/xrf/trip-5-lab/'

# Regex to extract Site ID from filename
# Matches numbers at the start of the filename, potentially identifying 'V' prefix or 'Dr' suffix.
# Examples: 10.tsv -> 10, 1Dr1.tsv -> 1, V18Dr3... -> 18
SITE_ID_REGEX = re.compile(r'^V?(\d+)')

def get_site_id(filename):
    match = SITE_ID_REGEX.match(filename)
    if match:
        return match.group(1)
    return None

def determine_type(formula):
    # If formula is a simple element symbol (e.g., Si, Fe, Ca)
    if re.match(r'^[A-Z][a-z]?$', formula):
        return 'Element'
    # If formula contains numbers or looks like an oxide (e.g., SiO2, Fe2O3)
    # Also LE (Light Elements)
    if formula == 'LE':
        return 'Element' # Treated as element in vanta_data usually
    return 'Compound'

def process_file(filepath):
    filename = os.path.basename(filepath)
    site_id = get_site_id(filename)
    
    if not site_id:
        print(f"Skipping {filename}: Could not extract Site ID")
        return

    print(f"Processing {filename} as Site {site_id}")

    data_rows = []
    
    try:
        with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
            # Read lines and filter out empty lines or metadata lines that don't look like data header or rows
            lines = [line.strip() for line in f if line.strip()]
            
        # Find the indices of lines that start with "Formula"
        header_indices = [i for i, line in enumerate(lines) if line.startswith('Formula')]
        
        if not header_indices:
            print(f"Warning: No 'Formula' header found in {filename}")
            return

        for i in header_indices:
            # Parse the section
            # The header is at line i
            # Data follows until we hit a line that doesn't look like data or end of file
            # Header usually: Formula, Z, Concentration, Status, ...
            
            header_line = lines[i]
            headers = [h.strip() for h in header_line.split('\t')]
            
            # Identify columns
            try:
                col_formula = headers.index('Formula')
                col_conc = headers.index('Concentration')
                # Error column might be 'Stat. error' or similar
                col_error = -1
                for idx, h in enumerate(headers):
                    if 'Stat. error' in h:
                        col_error = idx
                        break
            except ValueError:
                print(f"Warning: Missing expected columns in section starting at line {i+1} in {filename}")
                continue

            # Iterate data rows
            current_idx = i + 1
            while current_idx < len(lines):
                line = lines[current_idx]
                row = [c.strip() for c in line.split('\t')]
                
                # Check if it's a valid data row
                # Should have enough columns and the first column should look like a formula
                if len(row) <= max(col_formula, col_conc, col_error):
                    break
                
                formula = row[col_formula]
                # Stop if we hit metadata lines like "Material" or empty formula
                if not formula or formula.startswith('Material') or formula.startswith('Mode'):
                    break
                
                # Extract data
                conc = row[col_conc]
                error = row[col_error] if col_error != -1 else '0'
                
                # Basic validation: conc should be a number (or empty string if missing)
                # Some files might have empty concentration for some elements
                if not conc:
                    current_idx += 1
                    continue
                    
                analyte_type = determine_type(formula)
                
                # Add to data list
                data_rows.append({
                    'Analyte': formula,
                    'Concentration': conc,
                    'Error': error,
                    'Type': analyte_type
                })
                
                current_idx += 1

    except Exception as e:
        print(f"Error reading {filename}: {e}")
        return

    if not data_rows:
        print(f"Warning: No data extracted from {filename}")
        return

    # Write output TSV
    # Sanitize filename for inclusion in output name
    name_root = os.path.splitext(filename)[0]
    sanitized_name = re.sub(r'[^a-zA-Z0-9]', '_', name_root)
    
    output_filename = f"Site_{site_id}_{sanitized_name}_lab_repeat.tsv"
    output_path = os.path.join(OUTPUT_DIR, output_filename)
    
    with open(output_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=['Analyte', 'Concentration', 'Error', 'Type'], delimiter='\t')
        writer.writeheader()
        writer.writerows(data_rows)
        
    print(f"Saved {output_filename}")

def main():
    files = glob.glob(os.path.join(INPUT_DIR, '*.tsv'))
    print(f"Found {len(files)} files in {INPUT_DIR}")
    
    for file in files:
        process_file(file)

if __name__ == '__main__':
    main()
