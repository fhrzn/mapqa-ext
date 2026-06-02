# SEA-MapQA

## Generating Dataset
First, make sure you have access to Overpass API.

Self-hosted: [read here](https://github.com/wiktorn/Overpass-API#how-to-use-this-image)

Public API: [read here](https://wiki.openstreetmap.org/wiki/Overpass_API)

Then, run the script:
```bash
python -m src.pipelines.overpass_api_query --country [country_name] --output-path [json_output_path]
```

Example:
```bash
python -m src.pipelines.overpass_api_query --country Singapore --output-path dataset/sea-mapqa/singapore.json
```