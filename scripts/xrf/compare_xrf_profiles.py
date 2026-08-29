import os
import glob
import re
import csv
import sys
import math

# Directories
LAB_DATA_DIR = 'data/processed/xrf/trip-5-lab/'
FIELD_DATA_BASE_DIR = 'data/processed/xrf/'

def load_lab_data_runs(site_id):
    """
    Loads lab measurements for a given Site ID, separated by file (run).
    Returns a list of dicts: [{'source': filename, 'data': {analyte: concentration}}]
    """
    pattern = os.path.join(LAB_DATA_DIR, f"Site_{site_id}_*_lab_repeat.tsv")
    files = glob.glob(pattern)
    
    runs = []
    
    for filepath in files:
        filename = os.path.basename(filepath)
        current_data = {}
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f, delimiter='\t')
                for row in reader:
                    if row['Type'] != 'Element':
                        continue
                    
                    analyte = row['Analyte']
                    if analyte == 'LE': continue
                        
                    try:
                        conc = float(row['Concentration'])
                    except ValueError:
                        continue
                        
                    # If multiple entries for same analyte in one file (unlikely for processed), take last or average?
                    # Processed file should be unique per analyte usually, but let's just overwrite
                    current_data[analyte] = conc
            
            if current_data:
                runs.append({'source': filename, 'data': current_data})
                
        except Exception as e:
            print(f"Error reading lab file {filepath}: {e}")
            
    return runs

def load_field_data_runs(site_id):
    """
    Loads field measurements for a given Site ID, separated by Test run.
    Returns a list of dicts: [{'source': test_dir_name, 'data': {analyte: concentration}}]
    """
    site_dir = os.path.join(FIELD_DATA_BASE_DIR, f"Site_{site_id}")
    if not os.path.exists(site_dir):
        return []
        
    test_dirs = glob.glob(os.path.join(site_dir, "Test_*"))
    runs = []
    
    for test_dir in test_dirs:
        test_name = os.path.basename(test_dir)
        # Assuming one vanta_data csv per test dir, or merge them if split?
        # Usually it's one main data file.
        csv_files = glob.glob(os.path.join(test_dir, "vanta_data_*.csv"))
        
        current_data = {}
        
        for filepath in csv_files:
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    reader = csv.DictReader(f, delimiter=',')
                    for row in reader:
                        if 'Type' in row and row['Type'] != 'Element':
                            continue
                        
                        analyte = row.get('Analyte')
                        if not analyte or analyte == 'LE': continue

                        try:
                            conc = float(row['Concentration'])
                        except ValueError:
                            continue
                            
                        # If multiple files in one test dir, we merge them into one 'run'
                        current_data[analyte] = conc
            except Exception as e:
                print(f"Error reading field file {filepath}: {e}")
        
        if current_data:
            runs.append({'source': test_name, 'data': current_data})
            
    return runs

def calculate_correlation(vec1, vec2):
    if len(vec1) != len(vec2) or len(vec1) < 2:
        return 0.0
    n = len(vec1)
    mean1 = sum(vec1) / n
    mean2 = sum(vec2) / n
    
    numerator = sum((x - mean1) * (y - mean2) for x, y in zip(vec1, vec2))
    denom1 = sum((x - mean1) ** 2 for x in vec1)
    denom2 = sum((y - mean2) ** 2 for y in vec2)
    
    if denom1 == 0 or denom2 == 0:
        return 0.0
        
    return numerator / math.sqrt(denom1 * denom2)

def main():
    # Header
    print(f"{ 'Site':<5} | { 'Max Corr':<10} | { 'Best Lab Source':<40} | { 'Best Field Source':<20}")
    print("-" * 85)
    
    sites_to_check = range(1, 61)
    
    for site_id in sites_to_check:
        lab_runs = load_lab_data_runs(site_id)
        field_runs = load_field_data_runs(site_id)
        
        if not lab_runs or not field_runs:
            continue
            
        best_corr = -1.0
        best_lab = "N/A"
        best_field = "N/A"
        
        for l_run in lab_runs:
            for f_run in field_runs:
                # Find common analytes
                l_data = l_run['data']
                f_data = f_run['data']
                
                common = sorted(set(l_data.keys()) & set(f_data.keys()))
                if len(common) < 3:
                    continue
                    
                vec_l = [l_data[k] for k in common]
                vec_f = [f_data[k] for k in common]
                
                corr = calculate_correlation(vec_l, vec_f)
                
                if corr > best_corr:
                    best_corr = corr
                    best_lab = l_run['source']
                    best_field = f_run['source']
        
        if best_corr > -1.0:
            print(f"{site_id:<5} | {best_corr:.4f}     | {best_lab:<40} | {best_field:<20}")
        else:
            print(f"{site_id:<5} | {'N/A':<10} | {'(No matching data)':<40} | {'-':<20}")

if __name__ == '__main__':
    main()