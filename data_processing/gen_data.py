import pandas as pd
import numpy as np
import random
from datetime import datetime, timedelta

# Optional live database-derived generation profile.
# from database_referral import load_generation_profile
#
# database_profile = load_generation_profile()
#
# def refresh_database_profile():
#     return load_generation_profile()
#
# def database_location_weight(lat, lon):
#     round_coordinates = database_profile["metadata"]["round_coordinates"]
#     key = f"{lat:.{round_coordinates}f},{lon:.{round_coordinates}f}"
#     return database_profile["location_weights"].get(
#         key,
#         database_profile["defaults"]["location_weight"],
#     )
#
# def database_hourly_factor(timestamp):
#     day_type = "weekend" if timestamp.weekday() >= 5 else "weekday"
#     return database_profile["hourly_factors"].get(day_type, {}).get(
#         str(timestamp.hour),
#         database_profile["defaults"]["hourly_factor"],
#     )
#
# def database_collection_timestamps(current_day):
#     day_type = "weekend" if current_day.weekday() >= 5 else "weekday"
#     slots = database_profile["collection_times"].get(day_type)
#     if not slots:
#         slots = database_profile["defaults"]["collection_times"]
#
#     return [
#         current_day.replace(
#             hour=int(slot["hour"]),
#             minute=int(slot["minute"]),
#             second=0,
#         )
#         for slot in slots
#     ]

# 1. Load the provided OpenStreetMap intersection nodes
raw_nodes_data = """
5543290536,(34.8120598, 135.5609883)
5543290537,(34.8120598, 135.5611754)
554329047,(34.8108243, 135.5637906)
5543290553,(34.8110551, 135.5628206)
5543290556,(34.8114154, 135.5623462)
5543290564,(34.8121202, 135.5611755)
5543290570,(34.8119625, 135.5607282)
5550314949,(34.8118532, 135.5618445)
5740435959,(34.8110551, 135.5624413)
5740435962,(34.8107453, 135.5630163)
5740435963,(34.8105698, 135.5630553)
5740435968,(34.8106809, 135.5632193)
5740435971,(34.8106811, 135.5635319)
5740435973,(34.8103791, 135.5620647)
5740435974,(34.8114302, 135.5620647)
5740435977,(34.8110319, 135.562575)
5740435982,(34.8119781, 135.5611887)
6877151246,(34.8108985, 135.5620647)
9457418770,(34.8085471, 135.5595907)
9776167898,(34.8115486, 135.5612113)
9776167899,(34.8115794, 135.5612128)
9776176491,(34.8117993, 135.5616141)
9776176492,(34.811736, 135.5615584)
9776188884,(34.8119542, 135.5607628)
9776203778,(34.8101524, 135.5618665)
9776203780,(34.8101518, 135.5599773)
9777592354,(34.810334, 135.5637954)
9777592362,(34.8109739, 135.5627559)
9777592376,(34.8103319, 135.5635336)
9777592377,(34.8103214, 135.5629004)
9777592383,(34.8105145, 135.5619712)
9777592452,(34.8120655, 135.5614013)
9777592453,(34.8120201, 135.5611754)
9781202954,(34.8099869, 135.5618668)
9784464960,(34.809684, 135.5598092)
9784464961,(34.8097266, 135.561015)
9784464967,(34.8095185, 135.5610485)
9800535402,(34.8111705, 135.5626265)
9800535937,(34.8118771, 135.5618097)
9801581574,(34.8101523, 135.5605957)
9801581576,(34.8100646, 135.5604614)
9801581577,(34.8101527, 135.5610122)
9801624230,(34.8101528, 135.5619684)
9801624232,(34.8101709, 135.5634561)
9801624234,(34.8099872, 135.5633934)
9801624235,(34.8114764, 135.5620256)
9801680792,(34.8092517, 135.5618663)
9801680793,(34.8092536, 135.5622549)
9803084686,(34.8101516, 135.5601059)
9803094374,(34.8092525, 135.5620366)
9803094385,(34.8097947, 135.5618688)
9803106921,(34.8081124, 135.5618743)
9803106963,(34.8119447, 135.5609311)
9803106964,(34.8118318, 135.5609959)
9803106965,(34.8116748, 135.560929)
9805237101,(34.8112944, 135.56097)
9805237116,(34.8101522, 135.5606819)
9805277417,(34.810358, 135.5606798)
9805277418,(34.810358, 135.5607013)
9805277419,(34.8108174, 135.5606773)
9805277420,(34.8108173, 135.5607032)
9805277422,(34.8113012, 135.56097)
9805277424,(34.8116524, 135.5609926)
9805959733,(34.8099864, 135.5620731)
9805959734,(34.8101532, 135.5623655)
9805959735,(34.8100997, 135.5623655)
9805959736,(34.8101519, 135.5616526)
9805959737,(34.8101967, 135.5616516)
9805959738,(34.8104207, 135.5619708)
9805959740,(34.8104207, 135.5619054)
9805964182,(34.8105152, 135.5617121)
9805964183,(34.8105149, 135.5617983)
9805964187,(34.8106175, 135.5617113)
9805964188,(34.8098642, 135.5618672)
9805964190,(34.8099632, 135.5617005)
9806400259,(34.8101979, 135.5635027)
9806400264,(34.8092773, 135.562534)
9806400290,(34.8083382, 135.5603621)
9807862941,(34.8097258, 135.5601075)
9807862949,(34.8097518, 135.5600025)
9807862978,(34.8095166, 135.5608112)
9810909161,(34.8096958, 135.5601076)
9810909162,(34.8097246, 135.5598238)
9810909163,(34.8099988, 135.5599223)
9810909179,(34.8116719, 135.5605994)
9810909180,(34.8117067, 135.5606148)
9813713820,(34.8074828, 135.5618837)
9826745715,(34.8101543, 135.5631533)
9826747617,(34.8100998, 135.5629898)
9826747619,(34.8101976, 135.5616988)
9826747620,(34.810152, 135.5616992)
9827315252,(34.8108241, 135.5637457)
9827508358,(34.8115456, 135.5616531)
9827635222,(34.8096831, 135.5599331)
9827635232,(34.8084436, 135.5599143)
9827635233,(34.8089451, 135.5597834)
9827635234,(34.8089451, 135.5598084)
9828398965,(34.8101974, 135.5637945)
9829639446,(34.8104137, 135.5635322)
9829639449,(34.8104139, 135.5637942)
12328883126,(34.808486, 135.5596232)
12849056136,(34.8099601, 135.5635048)
"""

# Parse node input
nodes = []
for line in raw_nodes_data.strip().split('\n'):
    node_id, coords = line.split(',(')
    lat, lon = coords.replace(')', '').split(',')
    nodes.append({'Node_ID': int(node_id.strip()), 'Latitude': float(lat), 'Longitude': float(lon)})

df_nodes = pd.DataFrame(nodes)

# 2. Establish spatial weights based on real campus layout
def generate_base_spatial_weight(lat, lon):
    if lat > 34.8115 and lon < 135.5615:
        return random.uniform(1.8, 2.5)       # Main JR Station Commuter Route (High)
    elif 34.8098 <= lat <= 34.8112 and 135.5610 <= lon <= 135.5625:
        return random.uniform(2.2, 3.2)       # Central Courtyard & Class Hubs (Max Traffic)
    elif lat < 34.8095 and lon < 135.5605:
        return random.uniform(0.15, 0.45)     # Quiet Park Alley (Low)
    elif lon > 135.5630:
        return random.uniform(0.10, 0.35)     # Far Eastern Border Alleys (Very Low)
    else:
        return random.uniform(0.5, 1.2)       # Secondary Inner Paths (Medium)

df_nodes['base_weight'] = df_nodes.apply(lambda r: generate_base_spatial_weight(r['Latitude'], r['Longitude']), axis=1)

# Database-derived alternative:
# df_nodes['base_weight'] = df_nodes.apply(
#     lambda r: database_location_weight(r['Latitude'], r['Longitude']),
#     axis=1,
# )

# 3. Build 3-week time loop with irregular intervals
start_date = datetime(2026, 5, 11)  # Starts on a Monday
dataset_records = []

for day_idx in range(60):
    current_day = start_date + timedelta(days=day_idx)
    is_weekend = current_day.weekday() >= 5

    # Database-derived live refresh alternative:
    # if day_idx == 0 or day_idx % 1 == 0:
    #     database_profile = refresh_database_profile()
    
    # Stagger manual collection counts
    num_sessions = random.randint(1, 2) if is_weekend else random.randint(4, 6)
    # Generate irregular decimal times between 8:00 AM and 6:30 PM
    decimal_hours = sorted([random.uniform(8.0, 18.5) for _ in range(num_sessions)])

    # Database-derived fixed collection times alternative:
    # collection_timestamps = database_collection_timestamps(current_day)
    # decimal_hours = [
    #     ts.hour + ts.minute / 60.0
    #     for ts in collection_timestamps
    # ]
    
    for h in decimal_hours:
        hr = int(h)
        mn = int((h - hr) * 60)
        timestamp = current_day.replace(hour=hr, minute=mn, second=0)

        # Database-derived fixed collection times alternative:
        # timestamp = collection_timestamps[decimal_hours.index(h)]
        
        # Calculate behavioral time multiplier
        if (8.5 <= h <= 9.1) or (12.0 <= h <= 13.1) or (14.3 <= h <= 14.8) or (16.0 <= h <= 16.5):
            time_factor = 2.6  # High flow: Class transitions and lunchtime
        elif (9.1 < h < 12.0) or (13.1 < h < 14.3) or (14.8 < h < 16.0):
            time_factor = 0.75 # Quiet: Active lecture hours
        else:
            time_factor = 0.35 # Slow: Early morning / late evening
            
        if is_weekend:
            time_factor *= 0.12 # Massive weekend activity penalty

        # Database-derived alternative:
        # time_factor = database_hourly_factor(timestamp)
            
        # Add random human variance to the observation time window
        time_factor *= random.uniform(0.85, 1.15)
        
        # 4. Generate random integer counts for every single node at this observation point
        for _, node in df_nodes.iterrows():
            # Mean expected count for Poisson distribution
            lambda_pedestrians = node['base_weight'] * time_factor * 16.5
            count = np.random.poisson(lambda_pedestrians)
            
            # Format outputs according to target pipeline requirements
            # Longitude must be placed FIRST in WKT string: POINT(lon lat)
            location_wkt = f"POINT({node['Longitude']:.7f} {node['Latitude']:.7f})"
            # Include Tokyo time-offset (+09:00) so that pd.to_datetime parses it accurately
            timestamp_iso = timestamp.strftime('%Y-%m-%dT%H:%M:%S+09:00')
            
            dataset_records.append({
                'TIMESTAMPTZ': timestamp_iso,
                'Koordinaten [GEOGRAPHY]': location_wkt,
                'COUNT [INT]': count
            })

# Convert to DataFrame
final_df = pd.DataFrame(dataset_records)

# Insert the Primary Key column at position 0
final_df.insert(0, 'Primary Key', range(1, len(final_df) + 1))

# Save file (using standard comma separator to ensure compatibility with fit_fourier.py)
output_filename = 'data.csv'
final_df.to_csv(output_filename, index=False)

print(f"Success! Generated {len(final_df)} structured data entries in '{output_filename}' matching project format schema.")
