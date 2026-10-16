# Third-party notices

## Schema.org vocabulary

`seo_local/vocabulary/schema-30.1.json` is a compact derivative of the
Schema.org 30.1 vocabulary, published by the Schema.org project and its
sponsors (Google, Microsoft, Yahoo and Yandex).

- Source: https://github.com/schemaorg/schemaorg/blob/1c4009f4da1de9443266bc7d332c28f1ff1d37fa/data/releases/30.1/schemaorg-current-https.jsonld
- Terms: https://schema.org/docs/terms.html
- License: Creative Commons Attribution-ShareAlike 3.0 Unported,
  https://creativecommons.org/licenses/by-sa/3.0/
- Legal code: https://creativecommons.org/licenses/by-sa/3.0/legalcode
- Changes: extracted type inheritance and property domain/range identifiers;
  omitted comments and unrelated RDF metadata; renamed compact keys.
- The derived vocabulary is distributed under **CC BY-SA 3.0**.
  No endorsement by Schema.org or its sponsors is implied.
- Rebuild with `scripts/build_vocabulary.py`; the output includes the source SHA-256.

## Lighthouse and chrome-launcher

Optional npm dependencies retain their Apache-2.0 licenses and notices:
https://github.com/GoogleChrome/lighthouse and
https://github.com/GoogleChrome/chrome-launcher.
All resolved dependencies are pinned in package-lock.json; their license
files are included when npm installs them. Chrome is separately installed
software, not redistributed in this repository.

## Interface assets (0.3)

- GSAP 3.15.0: https://gsap.com/standard-license/ — Standard no-charge license (not MIT). Vendored dist/gsap.min.js from the pinned npm package; license header preserved.
- Unbounded and Manrope variable fonts from @fontsource-variable 5.3.0, Cyrillic and Latin subsets, SIL Open Font License 1.1. License files in web/assets. Sources: https://fontsource.org/fonts/unbounded and https://fontsource.org/fonts/manrope.
- Scanner illustration is original CSS; no gallery images are distributed.
