const ISO_DATE_PREFIX = /^(\d{4})-(\d{2})-(\d{2})/;

function datePrefix(value: string | null | undefined): string | undefined {
  return ISO_DATE_PREFIX.exec((value ?? "").trim())?.[0];
}

/**
 * Time-independent trust check: the API explicitly marks the code verified and both of
 * its dates are well-formed. Lets the server drop unverified codes before they are
 * embedded in a page, not merely hidden by the client.
 */
export function isTrustedCoupon(
  coupon: { verified?: boolean | null; expires_at?: string | null; verified_at?: string | null },
): boolean {
  return coupon.verified === true && !!datePrefix(coupon.expires_at) && !!datePrefix(coupon.verified_at);
}

/**
 * Whether a code with both dates present has passed its expiry. Pages are cached for up
 * to a day, so this is what retires a code in the UI after the API stopped returning it.
 */
export function isCouponExpired(
  coupon: { expires_at?: string | null; verified_at?: string | null },
  today: string | null,
): boolean {
  const expiry = datePrefix(coupon.expires_at);
  if (!expiry || !datePrefix(coupon.verified_at)) return true;
  return today !== null && today > expiry;
}
