# ScreamscapeMobile

Proof of concept: a responsive, mobile-friendly version of [Screamscape](https://screamscape.com/)
that keeps the site's existing look.

**What's included:** the home page plus every Six Flags, Universal and Disney park page
(39 pages). Links to any other page go to the live site.

The site is published with GitHub Pages from the `docs/` folder.

## How it works

The live site is a 2008-era NetObjects Fusion build: a fixed 1240px layout made of nested
tables and spacer GIFs, with no `viewport` meta tag. `tools/build.py` reads the original
pages (saved in `_source/`), extracts each region and rebuilds the page with:

- semantic HTML: `header`, `nav`, `main`, `aside` and `footer`;
- **CSS Grid** for the page structure, sized from the original pixel widths, so the
  desktop view still matches the old layout;
- a **container query** that moves the "Track Record" column below the news when the
  content area gets narrow;
- fluid images (the masthead scales proportionally), with responsive iframes and social
  embeds;
- a collapsible menu on phones that reuses the original menu button images;
- percentage-positioned links in place of the masthead's social-icon image map.

| Width        | Layout                                                                 |
|--------------|------------------------------------------------------------------------|
| ≥ 1100px     | Original three-column desktop layout                                   |
| 760–1099px   | Welcome text moves below the banner; Track Record moves below the news |
| < 760px      | Single column, collapsible menu, larger text and links                 |

The text inside each page is unchanged. Ad units are replaced with labelled placeholders
in the same positions and sizes. Analytics and ad scripts are removed. Every page has
`noindex` set, so this copy won't compete with the real site in search results.

## Rebuilding

```sh
pip install beautifulsoup4
python tools/build.py
```

The stylesheet and menu script are in `tools/static/` and are copied into `docs/` at
build time. The list of pages to convert is in `tools/pages.txt`.
