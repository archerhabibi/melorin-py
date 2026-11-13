// Text helpers shared by admin-web and store-web (previously copied into both apps).

/** Persian / Arabic-Indic digits to ASCII. */
export const toEn = (s) =>
  String(s ?? '')
    .replace(/[۰-۹]/g, (d) => String('۰۱۲۳۴۵۶۷۸۹'.indexOf(d)))
    .replace(/[٠-٩]/g, (d) => String('٠١٢٣٤٥٦٧٨٩'.indexOf(d)));

/** ASCII digits only (Persian digits are normalised first). */
export const digits = (s) => toEn(s).replace(/\D/g, '');

/** Human message out of a failed Core response (`error.message`, FastAPI `detail`, or pydantic list). */
export async function errText(r, fallback) {
  try {
    const d = await r.json();
    const det = d?.detail;
    return (
      d?.error?.message ||
      (typeof det === 'string' ? det : det?.message) ||
      (Array.isArray(det) && det[0]?.msg?.replace(/^Value error, /, '')) ||
      fallback
    );
  } catch {
    return fallback;
  }
}
