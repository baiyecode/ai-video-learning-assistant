/**
 * Render the committed brand PNGs from their hand-authored HTML sources.
 *
 * Reproducible and offline: the local Playwright Chromium opens a file:// page,
 * the exact viewport is screenshotted at 1x, and the written PNG dimensions are
 * verified by reading the IHDR chunk. Run from ``frontend/``:
 *
 *   node scripts/render-brand-assets.mjs
 */
import { mkdir, readFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

import { chromium } from "@playwright/test";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

const targets = [
  {
    label: "brand icon",
    source: "brand/icon-512.html",
    output: "public/brand/icon-512.png",
    width: 512,
    height: 512,
    transparent: true,
  },
  {
    label: "share card",
    source: "brand/share-card.html",
    output: "public/brand/share-card.png",
    width: 1200,
    height: 630,
    transparent: false,
  },
];

function pngSize(buffer) {
  const signature = buffer.subarray(0, 8).toString("hex");
  if (signature !== "89504e470d0a1a0a") {
    throw new Error("rendered file is not a PNG");
  }
  return { width: buffer.readUInt32BE(16), height: buffer.readUInt32BE(20) };
}

const browser = await chromium.launch();
try {
  for (const target of targets) {
    const outputPath = path.join(root, target.output);
    await mkdir(path.dirname(outputPath), { recursive: true });

    const page = await browser.newPage({
      viewport: { width: target.width, height: target.height },
      deviceScaleFactor: 1,
    });
    await page.goto(pathToFileURL(path.join(root, target.source)).href, { waitUntil: "load" });
    await page.evaluate(() => document.fonts.ready.then(() => undefined));
    await page.screenshot({
      path: outputPath,
      clip: { x: 0, y: 0, width: target.width, height: target.height },
      omitBackground: target.transparent,
    });
    await page.close();

    const size = pngSize(await readFile(outputPath));
    if (size.width !== target.width || size.height !== target.height) {
      throw new Error(
        `${target.output}: expected ${target.width}x${target.height}, got ${size.width}x${size.height}`,
      );
    }
    console.log(`[brand] ${target.label}: ${target.output} ${size.width}x${size.height}`);
  }
} finally {
  await browser.close();
}
