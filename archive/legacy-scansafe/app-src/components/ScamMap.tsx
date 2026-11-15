"use client";

// Client-only (loaded with next/dynamic ssr:false): Leaflet touches window at import time.
import { useEffect, useRef } from "react";
import L from "leaflet";
import { MapContainer, TileLayer, useMap } from "react-leaflet";
import "leaflet/dist/leaflet.css";
import "leaflet.markercluster/dist/MarkerCluster.css";
import { percent, scamLabel, timeAgo } from "@/lib/labels";
import type { Pin } from "@/lib/types";

function esc(s: string): string {
  return s.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c] as string);
}

const pinIcon = L.divIcon({
  className: "scam-pin",
  html:
    '<svg width="34" height="46" viewBox="0 0 34 46" aria-hidden="true"><path d="M17 1C8.2 1 1 8 1 16.8 1 29 17 45 17 45s16-16 16-28.2C33 8 25.8 1 17 1z" fill="#c0262d" stroke="#fff" stroke-width="2"/><text x="17" y="23" text-anchor="middle" font-size="18" font-weight="900" fill="#fff" font-family="Arial">!</text></svg>',
  iconSize: [34, 46],
  iconAnchor: [17, 45],
  popupAnchor: [0, -40],
});

const pinKey = (p: Pin) => p.id ?? `${p.url}|${p.reported_at}`;

function popupHtml(p: Pin): string {
  return `<div class="pin-popup">
    <strong>${esc(scamLabel(p.scam_type))}</strong><br/>
    ${esc(percent(p.jev_score))} likely a scam<br/>
    <p style="margin:6px 0">${esc(p.explanation || "")}</p>
    ${p.domain ? `<div>Website: ${esc(p.domain)}</div>` : ""}
    <div>Reported ${esc(timeAgo(p.reported_at))}</div>
  </div>`;
}

function ClusterLayer({ pins, focus }: { pins: Pin[]; focus: Pin | null }) {
  const map = useMap();
  const groupRef = useRef<L.MarkerClusterGroup | null>(null);
  const markers = useRef(new Map<string, L.Marker>());

  useEffect(() => {
    let cancelled = false;
    (async () => {
      // leaflet.markercluster is a UMD plugin that expects a global L.
      (window as unknown as { L: typeof L }).L = L;
      await import("leaflet.markercluster");
      if (cancelled) return;
      groupRef.current?.remove();
      markers.current.clear();
      const group = L.markerClusterGroup({
        showCoverageOnHover: false,
        iconCreateFunction: (c) =>
          L.divIcon({
            html: `<div aria-hidden="true">${c.getChildCount()}</div>`,
            className: "marker-cluster-custom",
            iconSize: L.point(46, 46),
          }),
      });
      for (const p of pins) {
        const m = L.marker(p.location as L.LatLngTuple, {
          icon: pinIcon,
          title: `${scamLabel(p.scam_type)}, reported ${timeAgo(p.reported_at)}`,
          alt: `${scamLabel(p.scam_type)} reported here`,
          keyboard: true,
        });
        // 260px keeps the popup inside the map on a 375px-wide phone.
        m.bindPopup(popupHtml(p), { maxWidth: 260, autoPanPadding: [12, 12] });
        group.addLayer(m);
        markers.current.set(pinKey(p), m);
      }
      group.addTo(map);
      groupRef.current = group;
    })();
    return () => {
      cancelled = true;
      groupRef.current?.remove();
      groupRef.current = null;
    };
  }, [map, pins]);

  useEffect(() => {
    if (!focus) return;
    const m = markers.current.get(pinKey(focus));
    const g = groupRef.current;
    if (m && g) g.zoomToShowLayer(m, () => m.openPopup());
    else map.setView(focus.location as L.LatLngTuple, 17);
  }, [focus, map]);

  return null;
}

function Recenter({ center }: { center: [number, number] }) {
  const map = useMap();
  useEffect(() => {
    map.setView(center, map.getZoom());
  }, [center, map]);
  return null;
}

interface Props {
  center: [number, number];
  pins: Pin[];
  focus: Pin | null;
}

export default function ScamMap({ center, pins, focus }: Props) {
  return (
    <MapContainer center={center} zoom={14} scrollWheelZoom style={{ height: "100%", width: "100%" }} aria-label="Map of reported scam QR codes">
      <TileLayer
        attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
        url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
      />
      <Recenter center={center} />
      <ClusterLayer pins={pins} focus={focus} />
    </MapContainer>
  );
}
