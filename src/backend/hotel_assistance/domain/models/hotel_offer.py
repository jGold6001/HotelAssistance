"""One property returned by the hotel backend.

Display data only: the assistant never derives, adjusts or invents any of
these values, it only passes through what the backend reported.
"""

from pydantic import BaseModel


class HotelOffer(BaseModel):
    apartment: str
    address: str
    price: str
