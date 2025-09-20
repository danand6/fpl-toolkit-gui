import { useEffect, useRef } from 'react';
import * as d3 from 'd3';

function defaultValueFormatter(value) {
  if (Number.isNaN(value)) return '';
  if (Math.abs(value) >= 100) {
    return d3.format('.0f')(value);
  }
  return d3.format('.2f')(value);
}

export default function BarChart({
  data,
  width = 720,
  height = 360,
  color = '#38bdf8',
  valueFormatter = defaultValueFormatter,
  valueLabel
}) {
  const containerRef = useRef(null);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const cleanData = Array.isArray(data)
      ? data.filter((d) => Number.isFinite(d.value))
      : [];

    d3.select(container).selectAll('*').remove();

    if (!cleanData.length) {
      return;
    }

    const margin = { top: 24, right: 32, bottom: 44, left: 160 };
    const innerWidth = Math.max(width - margin.left - margin.right, 120);
    const innerHeight = Math.max(height - margin.top - margin.bottom, 120);

    const svg = d3
      .select(container)
      .append('svg')
      .attr('viewBox', `0 0 ${width} ${height}`)
      .attr('role', 'img');

    const chart = svg.append('g').attr('transform', `translate(${margin.left}, ${margin.top})`);

    const maxValue = d3.max(cleanData, (d) => d.value) ?? 0;
    const xScale = d3
      .scaleLinear()
      .domain([0, maxValue === 0 ? 1 : maxValue * 1.1])
      .range([0, innerWidth]);

    const yScale = d3
      .scaleBand()
      .domain(cleanData.map((d) => d.label))
      .range([0, innerHeight])
      .padding(0.2);

    const gradientId = 'bar-gradient';
    const defs = svg.append('defs');
    const gradient = defs
      .append('linearGradient')
      .attr('id', gradientId)
      .attr('x1', '0%')
      .attr('x2', '100%')
      .attr('y1', '0%')
      .attr('y2', '0%');

    const baseColor = d3.color(color) ?? d3.color('#38bdf8');
    gradient
      .append('stop')
      .attr('offset', '0%')
      .attr('stop-color', baseColor.brighter(0.6));
    gradient
      .append('stop')
      .attr('offset', '100%')
      .attr('stop-color', baseColor.darker(0.6));

    chart
      .append('g')
      .attr('class', 'chart-axis chart-axis--y')
      .call(d3.axisLeft(yScale).tickSize(0))
      .selectAll('text')
      .attr('dy', '0.35em')
      .style('fill', '#e2e8f0');

    chart
      .append('g')
      .attr('class', 'chart-axis chart-axis--x')
      .attr('transform', `translate(0, ${innerHeight})`)
      .call(d3.axisBottom(xScale).ticks(6).tickFormat(valueFormatter))
      .selectAll('text')
      .style('fill', '#94a3b8');

    chart
      .selectAll('.chart-grid')
      .data(xScale.ticks(6))
      .join('line')
      .attr('class', 'chart-grid')
      .attr('x1', (d) => xScale(d))
      .attr('x2', (d) => xScale(d))
      .attr('y1', 0)
      .attr('y2', innerHeight)
      .attr('stroke', 'rgba(148, 163, 184, 0.2)');

    const barGroups = chart
      .selectAll('.chart-bar')
      .data(cleanData)
      .join('g')
      .attr('class', 'chart-bar')
      .attr('transform', (d) => `translate(0, ${yScale(d.label) ?? 0})`);

    barGroups
      .append('rect')
      .attr('height', yScale.bandwidth())
      .attr('width', (d) => xScale(d.value))
      .attr('rx', yScale.bandwidth() / 2.5)
      .attr('fill', `url(#${gradientId})`)
      .attr('opacity', 0.9);

    barGroups
      .append('text')
      .attr('x', (d) => xScale(d.value) + 8)
      .attr('y', yScale.bandwidth() / 2)
      .attr('dy', '0.35em')
      .attr('fill', '#f8fafc')
      .attr('font-size', 12)
      .text((d) => d.displayValue ?? valueFormatter(d.value));

    if (valueLabel) {
      svg
        .append('text')
        .attr('class', 'chart-caption')
        .attr('x', margin.left + innerWidth / 2)
        .attr('y', height - 6)
        .attr('text-anchor', 'middle')
        .attr('fill', '#94a3b8')
        .attr('font-size', 12)
        .text(valueLabel);
    }
  }, [data, width, height, color, valueFormatter, valueLabel]);

  return <div className="chart-container" ref={containerRef} />;
}
