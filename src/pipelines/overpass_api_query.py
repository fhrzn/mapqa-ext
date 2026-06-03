import asyncio
import json
import os
from argparse import ArgumentParser
from typing import List

import httpx
from geonamescache import GeonamesCache
from tqdm.asyncio import tqdm

from src.schema.schema import OSMPOI

POI_CLASSES = ["amenity", "shop", "tourism", "leisure", "office", "historic"]
DEFAULT_HOST = "http://100.69.181.117:4567/"
OVERPASS_ENDPOINT = "api/interpreter"
COUNTRY_ADMIN_MAPPING = {
    "Indonesia": {
        "country_code": "ID",
        "admin_level": 5,
    },
    "Thailand": {
        "country_code": "TH",
        "admin_level": 6,
    },
    "Vietnam": {
        "country_code": "VN",
        "admin_level": 6,
    },
    "Philippines": {
        "country_code": "PH",
        "admin_level": 5,
    },
    "Malaysia": {
        "country_code": "MY",
        "admin_level": 6,
    },
    "Singapore": {
        "country_code": "SG",
        "admin_level": 4,
    },
    "Myanmar": {
        "country_code": "MM",
        "admin_level": 5,
    },
    "Cambodia": {
        "country_code": "KH",
        "admin_level": 6,
    },
    "Laos": {
        "country_code": "LA",
        "admin_level": 5,
    },
    "Timor Leste": {"country_code": "TL", "admin_level": 5},
}


def parse_element(
    elem: dict, country: str, country_code: str, city: str
) -> OSMPOI | None:
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
        city=tags.get("addr:city") or tags.get("addr:district") or city["name"],
        country=tags.get("addr:country") or country,
        country_code=tags.get("addr:country_code") or country_code,
        bounding_box=bbox,
        extra_tags=tags,
    )


async def overpass_request(
    client: httpx.AsyncClient,
    url: str,
    timeout: int = 60,
    *,
    query: str,
):
    response = await client.post(
        url=url,
        data={"data": query},
        timeout=timeout,
        headers={"User-Agent": "mapqa-ext-sea"},
    )
    response.raise_for_status()
    return response.json()


async def get_cities(
    client: httpx.AsyncClient,
    url: str,
    timeout: int = 60,
    *,
    country_name: str,
    country_code: str,
    admin_level: str,
):
    query = f"""
        [out:json][timeout:120];
        area["ISO3166-1"="{country_code}"]->.country;
        (
            relation["boundary"="administrative"]
                    ["admin_level"="{admin_level}"]
                    (area.country);
        );
        out center tags;
    """.strip()

    try:
        res = await overpass_request(client, url, timeout, query=query)
        res = res.get("elements", [])
        cities = [
            {
                "relation_id": r["id"],
                "area_id": r["id"] + 3600000000,
                "name": r["tags"].get("name"),
                "country_code": country_code,
                "country": country_name["name"],
                "lat": r["center"].get("lat"),
                "lon": r["center"].get("lon"),
            }
            for r in res
        ]

        return cities

    except Exception as e:
        print(e)
        return


async def get_pois(
    client: httpx.AsyncClient,
    url: str,
    timeout: int = 60,
    *,
    item: dict,
    poi_classes: List[str],
):
    query = f"""
        [out:json][timeout:120];
        area({item.get("area_id")})->.city;
        (
            {"".join(f'    {elem}["{cls}"](area.city);' + chr(10) for cls in poi_classes for elem in ["node", "way", "relation"])}
        );
        out bb tags;
    """.strip()

    try:
        res = await overpass_request(client, url, timeout, query=query)
        res = res.get("elements", [])
        if not res:
            print(f"[WARN] POI query on `{item.get('name')}` returned an empty result.")
            return res

        pois = [
            p.model_dump()
            for elem in res
            if (
                p := parse_element(
                    elem, item.get("country"), item.get("country_code"), item
                )
            )
            is not None
        ]

        return pois

    except Exception as e:
        print(f"[ERROR] POI query on `{item.get('name')}` returned an error.")
        print(e)
        return


async def main(args):
    url = os.path.join(args.url, OVERPASS_ENDPOINT)
    gc = GeonamesCache()

    ### step 1: get city relations ###
    if os.path.exists(os.path.join(args.output_dir, "cities.json")):
        cities = json.loads(
            open(os.path.join(args.output_dir, "cities.json"), "r").read()
        )
    else:
        print("Get cities...")
        async with httpx.AsyncClient() as client:
            tasks = [
                get_cities(
                    client,
                    url,
                    country_name=gc.get_countries().get(v["country_code"]),
                    **v,
                )
                for v in COUNTRY_ADMIN_MAPPING.values()
            ]
            results = await tqdm.gather(*tasks)
        # merge result
        cities = [it for items in results for it in items]
        with open(os.path.join(args.output_dir, "cities.json"), "w") as f:
            f.write(json.dumps(cities, indent=4, ensure_ascii=False))

    ### step 2: get pois ###
    print("Get POIs...")
    semaphore = asyncio.Semaphore(50)

    async def _wrapper_get_poi(sem, client, url, item, poi_classes):
        async with sem:
            await asyncio.sleep(1)
            return await get_pois(client, url, item=item, poi_classes=poi_classes)

    async with httpx.AsyncClient() as client:
        tasks = [
            _wrapper_get_poi(
                semaphore, client, url, item=item, poi_classes=args.poi_classes
            )
            for item in cities
        ]

        results = await tqdm.gather(*tasks)
    # merge result
    all_pois = [item for sublist in results for item in sublist if sublist is not None]
    output_path = os.path.join(args.output_dir, "pois.json")
    with open(output_path, "w") as f:
        f.write(json.dumps(all_pois, indent=4))

    print(f"Successfully write output to: {output_path}")


if __name__ == "__main__":
    parser = ArgumentParser()
    parser.add_argument(
        "--poi-classes",
        nargs="+",
        type=str,
        default=POI_CLASSES,
        help="A list of POI classes",
    )
    parser.add_argument(
        "--output-dir", help="Output directory of generated files", required=True
    )
    parser.add_argument("--url", help="Overpass API URL", default=DEFAULT_HOST)
    args = parser.parse_args()
    asyncio.run(main(args))
