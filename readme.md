# SEA-MapQA

## Generating Dataset
First, make sure you have access to Overpass API.

> Self-hosted: [read here](https://github.com/wiktorn/Overpass-API#how-to-use-this-image)
>
>Public API: [read here](https://wiki.openstreetmap.org/wiki/Overpass_API)

Create .env file to store your Overpass API credential
```bash
OVERPASS_API_HOST = "http://<OVERPASS_API_HOST>/"
```

Then, run the script:
```bash
python -m src.pipelines.overpass_api_query --output-dir dataset/sea-mapqa/
```