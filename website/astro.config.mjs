import { defineConfig } from "astro/config";
import starlight from "@astrojs/starlight";

// Canonical origin and URL prefix for the deployed site. GitHub Pages serves
// project sites under /<repo>/, so telemonitor lives at
// https://zarguell.github.io/telemonitor/. Override with SITE / BASE_PATH
// env vars (or repo vars of the same name, passed through by the deploy
// workflow) if the site ever moves to a custom domain.
const site = process.env.SITE ?? "https://zarguell.github.io";
const base = process.env.BASE_PATH ?? "/telemonitor/";

export default defineConfig({
  site,
  base,
  trailingSlash: "never",
  integrations: [
    starlight({
      title: "telemonitor docs",
      description:
        "Documentation for installing, configuring, and operating Telemonitor.",
      favicon: "/favicon.svg",
      editLink: {
        baseUrl: "https://github.com/zarguell/telemonitor/edit/main/website/",
      },
      social: [
        {
          icon: "github",
          label: "GitHub",
          href: "https://github.com/zarguell/telemonitor",
        },
      ],
      sidebar: [
        {
          label: "Start here",
          items: [
            { slug: "docs" },
            { slug: "docs/quickstart" },
            { slug: "docs/installation" },
            { slug: "docs/configuration" },
          ],
        },
        {
          label: "Guides",
          items: [
            { slug: "docs/guides/configure-telegram" },
            { slug: "docs/guides/monitors-and-alerts" },
          ],
        },
        {
          label: "Operations",
          items: [
            { slug: "docs/architecture" },
            { slug: "docs/security" },
            { slug: "docs/api" },
            { slug: "docs/media-storage" },
          ],
        },
        {
          label: "Product",
          items: [{ slug: "docs/product-spec" }],
        },
      ],
    }),
  ],
  build: {
    assets: "_astro",
  },
});
