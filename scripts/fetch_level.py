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
          gold
          silver
          bronze
        }
      }
    }
    """
    response = requests.post(GRAPHQL_URL, json={'query': query, 'variables': {'hash': level_hash}})
    if response.status_code == 200:
        nodes = response.json().get('data', {}).get('levels', {}).get('nodes', [])
        return nodes[0] if nodes else None
    else:
        raise Exception(f"Query failed with code {response.status_code}. {response.text}")

def get_best_ghost_by_hash(level_hash):
    query = """
    query GetBestGhost($hash: String!) {
      levels(filter: { hash: { equalTo: $hash } }) {
        nodes {
          id
          records(orderBy: TIME_ASC, first: 1) {
            nodes {
              id
              time
              ghostUrl
            }
          }
        }
      }
    }
    """
    response = requests.post(GRAPHQL_URL, json={'query': query, 'variables': {'hash': level_hash}})
    if response.status_code == 200:
        data = response.json().get('data', {})
        levels = data.get('levels', {}).get('nodes', [])
        if levels:
            records = levels[0].get('records', {}).get('nodes', [])
            if records:
                return records[0].get('ghostUrl')
        return None
    else:
        raise Exception(f"Query failed with code {response.status_code}. {response.text}")

def download_file(url, output_path):
    try:
        response = requests.get(url)
        if response.status_code == 200:
            with open(output_path, 'wb') as f:
                f.write(response.content)
            return True
    except Exception as e:
        print(f"Download error: {e}")
    return False

if __name__ == "__main__":
    # Test with a known hash if available
    pass
