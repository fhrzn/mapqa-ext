import asyncio
import json
from typing import List
import httpx
from tqdm.asyncio import tqdm
from src.schema.schema import OSMPOI
from argparse import ArgumentParser
import os
from geonamescache import GeonamesCache


POI_CLASSES = ["amenity", "shop", "tourism", "leisure", "office", "historic"]
DEFAULT_HOST = "http://100.69.181.117:4567/"
OVERPASS_ENDPOINT = "api/interpreter"
CITY_LIST_PATH = "./dataset/cities.json"


def parse_element(elem: dict, country: str, country_code: str, city: str) -> OSMPOI | None:
    tags = elem.get("tags", {})

    poi_class, poi_type = None, None
    for cls in POI_CLASSES:
        if cls in tags:
            poi_class, poi_type = cls, tags[cls]
            break
    if not poi_class:
        return None

    if elem["type"] == "node":
        lat, lon = elem["lat"], elem["lon"]
        bbox = [lat, lon, lat, lon]
    else:
        b = elem.get("bounds", {})
        bbox = [b.get("minlat"), b.get("minlon"), b.get("maxlat"), b.get("maxlon")]
        lat = (bbox[0] + bbox[2]) / 2 if bbox[0] is not None else None
        lon = (bbox[1] + bbox[3]) / 2 if bbox[1] is not None else None

    return OSMPOI(
        osm_id=elem["id"],
        lat=lat,
        lon=lon,
        poi_class=poi_class,
        poi_type=poi_type,
        name=tags.get("name", ""),
        city=tags.get("addr:city") or tags.get("addr:district") or city,
        country=tags.get("addr:country") or country,
        country_code=tags.get("addr:country_code") or country_code,
        bounding_box=bbox,
    )


def build_query(city: str, poi_classes: List[str], admin_levels: List[int] = [4, 5, 6]):
    levels = "|".join(str(lvl) for lvl in admin_levels)
    return f"""
        [out:json][timeout:120];
        area["name"~"{city}"]["admin_level"~"{levels}"]->.city;
        (
            {"".join(f'    {elem}["{cls}"](area.city);' + chr(10) for cls in poi_classes for elem in ["node", "way", "relation"])}
        );
        out bb tags;
    """.strip()


async def query_poi(
    client: httpx.AsyncClient, url: str, country: str, country_code: str, city: str, poi_classes: List[str]
):
    query = build_query(city, poi_classes)
    await asyncio.sleep(5)
    response = await client.post(url, data={"data": query}, timeout=60, headers={"User-Agent": "mapqa-ext-sea"})
    try:
        elements = response.json().get("elements", [])
        if not elements:
            print(f"[WARN] POI query on {city} returned an empty result.")
            return elements
        
        pois = [p.model_dump() for elem in elements if (p := parse_element(elem, country, country_code, city)) is not None]

        return pois
    except Exception as e:
        print(response.content.decode())
        print(e)


async def main(args):
    url = os.path.join(args.url, OVERPASS_ENDPOINT)
    cities = json.loads(open(args.city_list_path, "r").read())
    cities = [c["name"] for c in cities if c["country"] == args.country]
    gc = GeonamesCache()
    country_code = gc.get_countries_by_names()[args.country]["iso"]

    async with httpx.AsyncClient() as client:
        tasks = [query_poi(client, url, args.country, country_code, city, args.poi_classes) for city in cities]

        results = await tqdm.gather(*tasks)

    all_pois = [item for sublist in results for item in sublist]
    with open(args.output_path, "w") as f:
        f.write(json.dumps(all_pois))

    print(f"Successfully write output to: {args.output_path}")


if __name__ == "__main__":
    parser = ArgumentParser()
    parser.add_argument(
        "--country", help="Country name that POIs want to collect", required=True
    )
    parser.add_argument(
        "--poi-classes",
        nargs="+",
        type=str,
        default=POI_CLASSES,
        help="A list of POI classes",
    )
    parser.add_argument(
        "--output-path", help="Output location of generated csv file", required=True
    )
    parser.add_argument("--url", help="Overpass API URL", default=DEFAULT_HOST)
    parser.add_argument("--city-list-path", default=CITY_LIST_PATH)
    args = parser.parse_args()
    asyncio.run(main(args))
