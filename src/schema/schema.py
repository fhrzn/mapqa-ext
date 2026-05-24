from typing import List

from pydantic import BaseModel


class OSMPOI(BaseModel):
    osm_id: int
    lat: float
    lon: float
    poi_class: str
    poi_type: str
    name: str
    city: str | None
    country: str
    country_code: str
    bounding_box: List[float]
