"use client";

import { useEffect, useRef, useState, type MouseEvent } from "react";
import type * as Leaflet from "leaflet";
import MapClient from "@/app/map/MapClient";
import { getPins } from "@/lib/api";
import type { Pin } from "@/lib/types";
import s from "./onepage.module.css";

type Mode = "pins" | "heat";
type LeafletModule = typeof Leaflet;

const ATLANTA: [number, number] = [33.79, -84.32];
const HEAT_RADIUS_KM = 25;
// Lime where reports are sparse, red where they cluster.
const GRADIENT = { 0.3: "#0ae448", 0.6: "#abff84", 1.0: "#c0262d" };

// Leaflet's plugin hook: every map created after this registers itself, so the heat layer can be laid over the
// map that the shared ScamMap component creates, without changing that component.
const mapListeners = new Set<(map: Leaflet.Map) => void>();
let hookInstalled = false;
async function loadLeaflet(): Promise<LeafletModule> {
  const L = (await import("leaflet")).default as LeafletModule;
  if (!hookInstalled) {
    hookInstalled = true;
    L.Map.addInitHook(function (this: Leaflet.Map) {
      mapListeners.forEach((fn) => fn(this));
    });
  }
  return L;
}

/**
 * The existing interactive map (search, "near me", live Typesense pins) with a Pins / Heatmap switch. The mouse
 * wheel scrolls the page until the map is clicked; then it pans and zooms the map until the pointer leaves it.
 */
export default function MapSection() {
  const [ready, setReady] = useState(false);
  const [active, setActive] = useState(false);
  const [mode, setMode] = useState<Mode>("pins");
  const [heatPins, setHeatPins] = useState<Pin[]>([]);
  const leafletRef = useRef<LeafletModule | null>(null);
  const mapRef = useRef<Leaflet.Map | null>(null);
  const heatRef = useRef<Leaflet.Layer | null>(null);
  const [mapVersion, setMapVersion] = useState(0);

  // Install the hook before the map is created, then render the map.
  useEffect(() => {
    let alive = true;
    const onMap = (map: Leaflet.Map) => {
      mapRef.current = map;
      map.once("unload", () => {
        if (mapRef.current === map) mapRef.current = null;
        heatRef.current = null;
      });
      setMapVersion((v) => v + 1);
    };
    mapListeners.add(onMap);
    void loadLeaflet().then((L) => {
      if (!alive) return;
      leafletRef.current = L;
      setReady(true);
    });
    void getPins(ATLANTA[0], ATLANTA[1], HEAT_RADIUS_KM).then((r) => { if (alive) setHeatPins(r.pins); });
    return () => {
      alive = false;
      mapListeners.delete(onMap);
    };
  }, []);

  // Show or hide the heat layer.
  useEffect(() => {
    const L = leafletRef.current;
    const map = mapRef.current;
    if (!L || !map) return;
    let cancelled = false;
    void (async () => {
      if (heatRef.current) {
        heatRef.current.remove();
        heatRef.current = null;
      }
      if (mode !== "heat" || !heatPins.length) return;
      // leaflet.heat is a plain script that attaches itself to a global L.
      (window as unknown as { L: LeafletModule }).L = L;
      await import("leaflet.heat");
      if (cancelled || mapRef.current !== map) return;
      // The map can be created before its box has its final width; refresh Leaflet's cached size first.
      map.invalidateSize();
      const points = heatPins.map((p) => [p.location[0], p.location[1], Math.max(0.4, p.jev_score ?? 1)] as [number, number, number]);
      heatRef.current = L.heatLayer(points, { radius: 40, blur: 30, maxZoom: 15, minOpacity: 0.35, gradient: GRADIENT }).addTo(map);
    })();
    return () => { cancelled = true; };
  }, [mode, heatPins, mapVersion]);

  function onClick(e: MouseEvent<HTMLDivElement>) {
    if (active) return;
    const wrap = e.currentTarget.querySelector(".map-wrap");
    const r = wrap?.getBoundingClientRect();
    if (r && e.clientX >= r.left && e.clientX <= r.right && e.clientY >= r.top && e.clientY <= r.bottom) setActive(true);
  }

  return (
    <>
      <div className={s.modeSwitch} role="group" aria-label="Map view">
        <button type="button" aria-pressed={mode === "pins"} onClick={() => setMode("pins")}>Pins</button>
        <button type="button" aria-pressed={mode === "heat"} onClick={() => setMode("heat")}>Heatmap</button>
        {mode === "heat" && <span className={s.modeNote}>Reported scams within {HEAT_RADIUS_KM} km. Lime = a few, red = many.</span>}
      </div>
      <div
        className={`${s.mapArea}${active ? "" : ` ${s.mapLocked}`}${mode === "heat" ? ` ${s.heatMode}` : ""}`}
        onClick={onClick}
        onMouseLeave={() => setActive(false)}
        {...(active ? { "data-lenis-prevent": "" } : {})}
      >
        {ready ? <MapClient /> : <p className="progress" role="status">Loading the map…</p>}
      </div>
    </>
  );
}
