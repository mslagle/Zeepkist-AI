import requests
import json
import os

GRAPHQL_URL = "https://graphql.zeepki.st"

def get_level_by_hash(level_hash):
    query = """
    query GetLevelByHash($hash: String!) {
      levels(filter: { hash: { equalTo: $hash } }) {
        nodes {
          id
          hash
        }
      }
    }
    """
    try:
        response = requests.post(GRAPHQL_URL, json={'query': query, 'variables': {'hash': level_hash}}, timeout=10)
        if response.status_code == 200:
            data = response.json().get('data', {})
            nodes = data.get('levels', {}).get('nodes', [])
            return nodes[0] if nodes else None
    except:
        pass
    return None

def get_best_ghost_by_hash(level_hash):
    print(f"Searching for ghost with level hash: {level_hash}")
    
    query = """
    query GetBestGhost($hash: String!) {
      levels(filter: { hash: { equalTo: $hash } }) {
        nodes {
          id
          records(orderBy: TIME_ASC, first: 1) {
            nodes {
              recordMedia {
                ghostUrl
              }
            }
          }
        }
      }
    }
    """
    try:
        response = requests.post(GRAPHQL_URL, json={'query': query, 'variables': {'hash': level_hash}}, timeout=10)
        if response.status_code == 200:
            data = response.json()
            levels = data.get('data', {}).get('levels', {}).get('nodes', [])
            if levels:
                records = levels[0].get('records', {}).get('nodes', [])
                if records:
                    media = records[0].get('recordMedia')
                    if media and media.get('ghostUrl'):
                        url = media.get('ghostUrl')
                        print(f"Found ghost URL: {url}")
                        return url
            print(f"No records found for level {level_hash}")
        else:
            print(f"Query failed with code {response.status_code}")
    except Exception as e:
        print(f"Query exception: {e}")

    return None

def download_file(url, output_path):
    if not url: return False
    print(f"Downloading ghost from: {url}")
    try:
        # Standardize URL
        if url.startswith("//"):
            url = "https:" + url
        
        response = requests.get(url, timeout=30)
        if response.status_code == 200:
            with open(output_path, 'wb') as f:
                f.write(response.content)
            return True
        else:
            print(f"Download failed with status: {response.status_code}")
    except Exception as e:
        print(f"Download error: {e}")
    return False

if __name__ == "__main__":
    # Example Test
    # print(get_best_ghost_by_hash("ea1"))
    pass
