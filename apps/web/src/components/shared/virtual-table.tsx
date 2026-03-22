"use client";

import { useState, useCallback, useRef, useMemo, type ReactNode } from "react";

interface VirtualTableProps<T> {
  /** Array of data items to render */
  data: T[];
  /** Height of each row in pixels */
  rowHeight: number;
  /** Height of the scrollable container in pixels */
  containerHeight: number;
  /** Render function for each row */
  renderRow: (item: T, index: number) => ReactNode;
  /** Table header content */
  headers: ReactNode;
  /** Number of extra rows to render above and below the viewport */
  overscan?: number;
  /** Optional className for the outer container */
  className?: string;
  /** Optional unique key extractor for items */
  getKey?: (item: T, index: number) => string | number;
}

export function VirtualTable<T>({
  data,
  rowHeight,
  containerHeight,
  renderRow,
  headers,
  overscan = 5,
  className = "",
  getKey,
}: VirtualTableProps<T>) {
  const [scrollTop, setScrollTop] = useState(0);
  const containerRef = useRef<HTMLDivElement>(null);

  const handleScroll = useCallback(() => {
    if (containerRef.current) {
      setScrollTop(containerRef.current.scrollTop);
    }
  }, []);

  const totalHeight = data.length * rowHeight;

  const { startIndex, endIndex, visibleItems } = useMemo(() => {
    const visibleCount = Math.ceil(containerHeight / rowHeight);

    const rawStart = Math.floor(scrollTop / rowHeight);
    const start = Math.max(0, rawStart - overscan);
    const end = Math.min(data.length - 1, rawStart + visibleCount + overscan);

    const items: { item: T; index: number }[] = [];
    for (let i = start; i <= end; i++) {
      items.push({ item: data[i], index: i });
    }

    return {
      startIndex: start,
      endIndex: end,
      visibleItems: items,
    };
  }, [scrollTop, data, rowHeight, containerHeight, overscan]);

  const topSpacerHeight = startIndex * rowHeight;
  const bottomSpacerHeight = Math.max(0, (data.length - endIndex - 1) * rowHeight);

  if (data.length === 0) {
    return (
      <div className={`rounded-lg border border-[hsl(var(--border))] ${className}`}>
        <div className="sticky top-0 z-10 bg-[hsl(var(--card))] border-b border-[hsl(var(--border))]">
          {headers}
        </div>
        <div
          className="flex items-center justify-center text-sm text-[hsl(var(--muted-foreground))]"
          style={{ height: containerHeight }}
        >
          No data to display
        </div>
      </div>
    );
  }

  return (
    <div className={`rounded-lg border border-[hsl(var(--border))] overflow-hidden ${className}`}>
      {/* Sticky header */}
      <div className="sticky top-0 z-10 bg-[hsl(var(--card))] border-b border-[hsl(var(--border))]">
        {headers}
      </div>

      {/* Scrollable body */}
      <div
        ref={containerRef}
        onScroll={handleScroll}
        className="overflow-y-auto"
        style={{ height: containerHeight }}
      >
        {/* Total scroll height container */}
        <div style={{ height: totalHeight, position: "relative" }}>
          {/* Top spacer */}
          <div style={{ height: topSpacerHeight }} aria-hidden="true" />

          {/* Visible rows */}
          {visibleItems.map(({ item, index }) => (
            <div
              key={getKey ? getKey(item, index) : index}
              style={{ height: rowHeight }}
              className="flex items-center"
            >
              {renderRow(item, index)}
            </div>
          ))}

          {/* Bottom spacer */}
          <div style={{ height: bottomSpacerHeight }} aria-hidden="true" />
        </div>
      </div>
    </div>
  );
}
