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
          name
          hash
          author
        }
      }
    }
    """
    try:
        response = requests.post(GRAPHQL_URL, json={'query': query, 'variables': {'hash': level_hash}}, timeout=10)
        if response.status_code == 200:
            nodes = response.json().get('data', {}).get('levels', {}).get('nodes', [])
            return nodes[0] if nodes else None
    except:
        pass
    return None

def get_best_ghost_by_hash(level_hash):
    print(f"Searching for ghost with level hash: {level_hash}")
    
    # Try searching for the best record directly
    query = """
    query GetBestGhost($hash: String!) {
      records(
        filter: { level: { hash: { equalTo: $hash } }, isValid: { equalTo: true } }
        orderBy: TIME_ASC
        first: 1
      ) {
        nodes {
          id
          time
          ghostUrl
        }
      }
    }
    """
    try:
        response = requests.post(GRAPHQL_URL, json={'query': query, 'variables': {'hash': level_hash}}, timeout=10)
        if response.status_code == 200:
            data = response.json().get('data', {})
            records = data.get('records', {}).get('nodes', [])
            if records and records[0].get('ghostUrl'):
                print(f"Found ghost via record search: {records[0]['ghostUrl']}")
                return records[0]['ghostUrl']
        else:
            print(f"Direct record query failed: {response.status_code}")
    except Exception as e:
        print(f"Direct record query exception: {e}")

    # Fallback: search via level
    query_fallback = """
    query GetLevelGhostFallback($hash: String!) {
      levels(filter: { hash: { equalTo: $hash } }) {
        nodes {
          id
          records(filter: { isValid: { equalTo: true } }, orderBy: TIME_ASC, first: 1) {
            nodes {
              ghostUrl
            }
          }
        }
      }
    }
    """
    try:
        response = requests.post(GRAPHQL_URL, json={'query': query_fallback, 'variables': {'hash': level_hash}}, timeout=10)
        if response.status_code == 200:
            data = response.json().get('data', {})
            levels = data.get('levels', {}).get('nodes', [])
            if levels:
                records = levels[0].get('records', {}).get('nodes', [])
                if records and records[0].get('ghostUrl'):
                    print(f"Found ghost via level fallback: {records[0]['ghostUrl']}")
                    return records[0]['ghostUrl']
    except Exception as e:
        print(f"Fallback query exception: {e}")

    return None

def download_file(url, output_path):
    print(f"Downloading from: {url}")
    try:
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
    # Test
    # print(get_best_ghost_by_hash("ea1"))
    pass
