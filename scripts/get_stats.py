import requests
import json

SPARQL_ENDPOINT = "http://localhost:8895/sparql"


def run_query(query):
    params = {"query": query, "format": "json"}
    try:
        response = requests.get(SPARQL_ENDPOINT, params=params)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"Error running query: {e}")
        return None


if __name__ == "__main__":
    print("\n--- Site 10 Top 5 Analytes ---")
    q = """
    PREFIX rak: <https://rubalkhali.science/kb/>
    PREFIX sio: <http://semanticscience.org/resource/>
    PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
    
    SELECT ?analyte ?concentration
    WHERE {
      ?process rdfs:label "Field XRF analysis (Test 5847) for Site 10 (Trip5)" .
      ?value sio:SIO_000232 ?process .
      ?value rak:RAK_2000012 ?concentration .
      ?quality sio:SIO_000215 ?value .
      ?quality a ?qc . ?qc rdfs:label ?analyte .
    }
    ORDER BY DESC(?concentration)
    LIMIT 5
    """
    res = run_query(q)
    if res:
        for b in res["results"]["bindings"]:
            print(f"{b['analyte']['value']}: {b['concentration']['value']}")
