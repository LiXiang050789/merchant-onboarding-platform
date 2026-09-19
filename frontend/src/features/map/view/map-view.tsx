"use client";

import "maplibre-gl/dist/maplibre-gl.css";
import maplibregl from "maplibre-gl";
import {RefreshCw} from "lucide-react";
import {useEffect, useRef} from "react";
import {useMapViewModel} from "@/features/map/view-model/use-map-view-model";

export function MapView() {
  const {city, setCity, status, setStatus, zoom, setZoom, query} = useMapViewModel();
  const containerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const markersRef = useRef<maplibregl.Marker[]>([]);

  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;
    mapRef.current = new maplibregl.Map({
      container: containerRef.current,
      center: [121.48, 31.23],
      zoom,
      interactive: true,
      style: {
        version: 8,
        sources: {},
        layers: [{id: "background", type: "background", paint: {"background-color": "#eef3f7"}}]
      }
    });
  }, [zoom]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !query.data) return;
    markersRef.current.forEach((marker) => marker.remove());
    markersRef.current = query.data.features.map((feature) => {
      const element = document.createElement("button");
      element.className = "cluster-marker";
      element.textContent = String(feature.properties.count);
      element.title = feature.properties.cluster_id;
      return new maplibregl.Marker({element}).setLngLat(feature.geometry.coordinates).addTo(map);
    });
  }, [query.data]);

  return (
    <div className="map-layout">
      <section className="panel" style={{padding: 16}}>
        <div className="toolbar">
          <select className="field" value={city} onChange={(event) => setCity(event.target.value)} aria-label="城市">
            <option value="shanghai">上海</option>
            <option value="beijing">北京</option>
            <option value="shenzhen">深圳</option>
            <option value="hangzhou">杭州</option>
            <option value="chengdu">成都</option>
          </select>
          <select className="field" value={status} onChange={(event) => setStatus(event.target.value)} aria-label="状态">
            <option value="published">published</option>
            <option value="batched">batched</option>
            <option value="processing">processing</option>
            <option value="failed">failed</option>
          </select>
          <input className="field" type="number" min={8} max={15} value={zoom} onChange={(event) => setZoom(Number(event.target.value))} aria-label="zoom" />
          <button className="icon-button" onClick={() => query.refetch()} title="刷新聚合">
            <RefreshCw size={16} />
          </button>
        </div>
        <div style={{marginTop: 16, color: "var(--muted)"}}>
          features: <b data-testid="map-features">{query.data?.features.length ?? 0}</b> · HTTP {query.data?.httpStatus ?? "-"}
        </div>
        <div className="cluster-list" style={{marginTop: 16}}>
          {query.data?.features.slice(0, 30).map((feature) => (
            <div className="cluster-row" key={feature.properties.cluster_id}>
              <span>{feature.properties.cluster_id}</span>
              <b>{feature.properties.count}</b>
            </div>
          ))}
        </div>
      </section>
      <section className="panel map-canvas" data-testid="map-canvas">
        <div ref={containerRef} className="maplibregl-map" />
      </section>
    </div>
  );
}
