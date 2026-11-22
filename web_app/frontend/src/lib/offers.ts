export interface OfferPrice {
  price: number;
  in_stock: boolean;
}

export function lowestAvailablePrice(offers: readonly OfferPrice[]): number | null {
  return offers.reduce<number | null>((lowest, offer) => {
    if (!offer.in_stock || !Number.isFinite(offer.price)) return lowest;
    return lowest === null ? offer.price : Math.min(lowest, offer.price);
  }, null);
}

export function sortOffers<T extends OfferPrice>(offers: readonly T[]): T[] {
  return [...offers].sort((a, b) => Number(b.in_stock) - Number(a.in_stock) || a.price - b.price);
}

export function retailerHref(value: string): string | null {
  try {
    const url = new URL(value);
    return url.protocol === "https:" || url.protocol === "http:" ? value : null;
  } catch {
    return null;
  }
}
