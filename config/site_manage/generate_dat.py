import os    
import json    
from datetime import datetime    
import pickle    
    
# 处理指定文件夹中的所有JSON文件，提取indexers和confs信息  
def process_json_files(folder_path):    
    indexers = []    
    confs = {}    
    for filename in os.listdir(folder_path):    
        if filename.endswith(".json"):    
            filepath = os.path.join(folder_path, filename)    
            try:    
                with open(filepath, "r", encoding="utf-8") as f:    
                    data = json.load(f)    
                    if isinstance(data, dict):    
                        indexer_data = {k: v for k, v in data.items() if k != "conf"}    
                        indexers.append(indexer_data)    
                        if "conf" in data:    
                            domain = data["domain"].split("//")[-1].split("/")[0]    
                            confs[domain] = data["conf"]    
                    else:    
                        print(f"Error: {filename} cannot be converted to a dictionary.")    
            except Exception as e:    
                print(f"Error reading {filename}: {str(e)}")    
    return indexers, confs    
    
# 将数据保存到JSON文件中，包括版本信息  
def save_data_to_json(data, json_path):    
    version = datetime.now().strftime("%Y%m%d%H%M")    
    result = {"version": version, "indexer": data[0], "conf": data[1]}    
    with open(json_path, "w", encoding="utf-8") as f:    
        json.dump(result, f, ensure_ascii=True, indent=4)    
    
# 将JSON文件转换为DAT文件（使用pickle进行序列化）  
def json_to_dat():    
    with open("sites.json", "r") as f:    
        all_dat = json.load(f)    
        with open("sites.dat", 'wb') as wf:    
            pickle.dump(all_dat, wf)    
    
# 格式化JSON文件，使其更易于阅读  
def format_json_file(file_path):    
    try:    
        with open(file_path, "r") as f:    
            data = json.load(f)    
    except json.JSONDecodeError as e:    
        print(f"Error decoding JSON in {file_path}: {e}")    
        return    
    with open(file_path, "w") as f:    
        json.dump(data, f, indent=4)    
    
# 格式化指定文件夹中的所有JSON文件  
def format_json_files_in_folder(folder_path):    
    for filename in os.listdir(folder_path):    
        file_path = os.path.join(folder_path, filename)    
        if os.path.isfile(file_path) and filename.lower().endswith(".json"):    
            format_json_file(file_path)    
    
# 创建或清空指定的sites.dat文件  
def create_or_clear_sites_file(sites_dat_path):    
    with open(sites_dat_path, "w") as f:    
        f.truncate(0) if os.path.exists(sites_dat_path) else None    
    
# 主程序入口，执行一系列操作：格式化JSON文件、处理JSON文件、保存数据、转换为DAT文件  
if __name__ == "__main__":    
    format_json_files_in_folder("sites")    
    create_or_clear_sites_file("sites.json")    
    indexers, confs = process_json_files("sites")    
    data = (indexers, confs)    
    save_data_to_json(data, "sites.json")    
    json_to_dat()
