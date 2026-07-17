"use client";

import { Treemap, ResponsiveContainer } from "recharts";

export interface SectorDatum {
  name: string;
  value: number;
  rawValue: number;
  color: string;
}

interface TreemapContentProps {
  x: number;
  y: number;
  width: number;
  height: number;
  name: string;
  value: number;
  color: string;
}

function CustomTreemapContent(props: TreemapContentProps) {
  const { x, y, width, height, name, value, color } = props;
  if (width < 40 || height < 30) return null;
  return (
    <g>
      <rect
        x={x}
        y={y}
        width={width}
        height={height}
        fill={color}
        stroke="hsl(var(--background))"
        strokeWidth={2}
        rx={4}
      />
      {width > 60 && height > 40 && (
        <>
          <text
            x={x + width / 2}
            y={y + height / 2 - 6}
            textAnchor="middle"
            fill="white"
            fontSize={12}
            fontWeight="600"
          >
            {name}
          </text>
          <text
            x={x + width / 2}
            y={y + height / 2 + 10}
            textAnchor="middle"
            fill="white"
            fontSize={10}
            opacity={0.8}
          >
            {value.toFixed(1)}%
          </text>
        </>
      )}
    </g>
  );
}

export default function SectorTreemap({ data }: { data: SectorDatum[] }) {
  return (
    <ResponsiveContainer width="100%" height="100%">
      <Treemap
        data={data}
        dataKey="value"
        aspectRatio={4 / 3}
        stroke="hsl(var(--background))"
        content={
          <CustomTreemapContent
            x={0}
            y={0}
            width={0}
            height={0}
            name=""
            value={0}
            color=""
          />
        }
      />
    </ResponsiveContainer>
  );
}
