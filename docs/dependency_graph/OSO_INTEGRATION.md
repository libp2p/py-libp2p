# OSO Integration Guide

This guide explains how to integrate py-libp2p's dependency graphs with Open Source Observer (OSO).

## Prerequisites

1. **OSO Account**: Create an account at https://www.opensource.observer/
1. **API Key**: Generate an API key from Account Settings
1. **Python Dependencies**: Install required packages
   ```bash
   pip install requests pyoso
   ```

## Getting Started

### 1. Get Your API Key

1. Visit https://www.opensource.observer/
1. Sign up or log in
1. Navigate to **Account Settings**
1. Generate a new **Personal API Key**
1. Save it securely

### 2. Set Up API Key

Choose one of these methods:

**Option A: Environment Variable**

```bash
export OSO_API_KEY='your-api-key-here'
```

**Option B: .env File**

```bash
echo 'OSO_API_KEY=your-api-key-here' >> .env
```

**Option C: Config File**

```bash
echo 'your-api-key-here' > .oso_config
```

### 3. Use the Integration Script

```bash
python3 scripts/integrate_oso.py
```

This script will:

- Load your API key
- Load the dependency graph JSON file
- Query OSO's API for project metrics
- Provide examples for further integration

## OSO API Methods

### GraphQL API

OSO provides a GraphQL API for querying project data. Example:

```python
import requests

query = """
query GetProject($projectName: String!) {
  project(name: $projectName) {
    name
    stars
    forks
    contributors
  }
}
"""

headers = {
    "Authorization": "Bearer YOUR_API_KEY",
    "Content-Type": "application/json",
}

response = requests.post(
    "https://api.opensource.observer/graphql",
    json={"query": query, "variables": {"projectName": "libp2p"}},
    headers=headers
)
```

### Python Library (pyoso)

OSO provides a Python library for easier integration:

```python
import pyoso

# Initialize client
client = pyoso.Client(api_key="YOUR_API_KEY")

# Query project data
project = client.get_project("libp2p")
print(project)
```

## Uploading Dependency Graphs

The dependency graph JSON files can be used with OSO in several ways:

### 1. Direct API Upload

Use OSO's GraphQL API to upload dependency data:

```python
from scripts.integrate_oso import load_dependency_graph, upload_dependency_graph

graph_data = load_dependency_graph("docs/dependency_graph/dependencies.json")
result = upload_dependency_graph(graph_data, api_key)
```

### 2. Data Warehouse Integration

OSO's data warehouse can ingest dependency graph data. Check OSO documentation for:

- Data warehouse access setup
- Schema requirements
- Upload procedures

### 3. Manual Upload

Some OSO features may support manual file uploads through their web interface.

## Available Dependency Graph Files

We generate two types of dependency graphs:

1. **Direct Dependencies** (`dependencies.json`)

   - Shows only first-level dependencies
   - 44 nodes, 52 edges
   - Star-shaped graph (all connect to libp2p)

1. **Transitive Dependencies** (`dependencies_transitive.json`)

   - Shows complete dependency tree
   - 56 nodes, 78 edges
   - Shows interconnections between packages

## Example Queries

### Query Project Metrics

```python
from scripts.integrate_oso import query_oso_graphql, load_api_key

api_key = load_api_key()

query = """
query {
  project(name: "libp2p") {
    name
    description
    stars
    forks
    contributors {
      count
    }
  }
}
"""

result = query_oso_graphql(query, api_key)
print(result)
```

### Query Dependency Health

```python
query = """
query {
  project(name: "libp2p") {
    dependencies {
      name
      version
      health {
        status
        vulnerabilities {
          severity
          count
        }
      }
    }
  }
}
"""
```

## Resources

- **OSO Website**: https://www.opensource.observer/
- **API Documentation**: https://docs.opensource.observer/docs/get-started/api/
- **Python Library**: https://pypi.org/project/pyoso/
- **GitHub Repository**: https://github.com/opensource-observer/oso
- **GraphQL Playground**: Check OSO documentation for GraphQL playground URL

## Troubleshooting

### API Key Issues

- Ensure your API key is correctly set
- Check that the API key hasn't expired
- Verify the key has necessary permissions

### Query Errors

- Review OSO's GraphQL schema documentation
- Check that project names match OSO's format
- Verify API endpoint URLs are correct

### Data Format Issues

- Ensure JSON files are valid
- Check that data structure matches OSO's expected format
- Review OSO's data integration documentation

## Next Steps

1. **Explore OSO Dashboard**: Visit https://www.opensource.observer/ to see available features
1. **Review API Documentation**: Check https://docs.opensource.observer/ for detailed API docs
1. **Join Community**: Connect with OSO community for support and updates
1. **Contribute**: Consider contributing dependency graph improvements back to OSO

## Support

For OSO-specific questions:

- Check OSO documentation: https://docs.opensource.observer/
- Open an issue on OSO's GitHub: https://github.com/opensource-observer/oso
- Contact OSO support through their website

For py-libp2p dependency graph questions:

- Open an issue: https://github.com/libp2p/py-libp2p/issues
- Start a discussion: https://github.com/libp2p/py-libp2p/discussions
