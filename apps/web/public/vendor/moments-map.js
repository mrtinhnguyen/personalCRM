(() => {
  'use strict';

  const WIDTH = 900;
  const HEIGHT = 520;
  const PADDING = 34;
  const MINIMUM_SPAN = 4;
  const REDUCED_MOTION = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  const SOURCE_LABELS = {wechat: 'WeChat', instagram: 'Instagram'};
  const SOURCE_COLORS = {wechat: '#e7040f', instagram: '#8a3ab9'};

  const number = value => {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : 0;
  };

  const placeName = place => place.poi || place.city || place.key;
  const formatNumber = value => Math.round(number(value)).toLocaleString('en-US');
  const yearsFor = place => new Set(
    (place.moments || []).map(moment => String(moment.at).slice(0, 4))
  );

  const initialize = async root => {
    if (root.dataset.momentsMapReady === 'true') {
      return;
    }
    root.dataset.momentsMapReady = 'true';

    const dataElement = root.querySelector('[data-moments-map-data]');
    const svgElement = root.querySelector('[data-moments-map-svg]');
    const frame = root.querySelector('[data-moments-map-frame]');
    const details = root.querySelector('[data-moments-map-details]');
    const tooltip = root.querySelector('[data-moments-map-tooltip]');
    const yearFilter = root.querySelector('[data-moments-map-year]');
    const sourceFilters = [...root.querySelectorAll('[data-moments-map-source]')];
    const resetButton = root.querySelector('[data-moments-map-reset]');
    if (!window.d3 || !dataElement || !svgElement || !frame) {
      if (details) {
        details.textContent = 'Map scripts did not load. Place details below still work.';
      }
      return;
    }

    const payload = JSON.parse(dataElement.textContent);
    const places = (payload.places || []).map(place => ({
      ...place,
      lat: number(place.lat),
      lon: number(place.lon),
      visits: number(place.visits),
      source: place.source || 'wechat',
      years: yearsFor(place),
    }));
    if (!places.length) {
      return;
    }

    const longitudes = places.map(place => place.lon);
    const latitudes = places.map(place => Math.max(-85, Math.min(85, place.lat)));
    let minimumLongitude = Math.min(...longitudes);
    let maximumLongitude = Math.max(...longitudes);
    let minimumLatitude = Math.min(...latitudes);
    let maximumLatitude = Math.max(...latitudes);
    const longitudePadding = Math.max(
      (MINIMUM_SPAN - (maximumLongitude - minimumLongitude)) / 2,
      0.5
    );
    const latitudePadding = Math.max(
      (MINIMUM_SPAN - (maximumLatitude - minimumLatitude)) / 2,
      0.5
    );
    minimumLongitude = Math.max(-180, minimumLongitude - longitudePadding);
    maximumLongitude = Math.min(180, maximumLongitude + longitudePadding);
    minimumLatitude = Math.max(-85, minimumLatitude - latitudePadding);
    maximumLatitude = Math.min(85, maximumLatitude + latitudePadding);

    const fitPoints = {
      type: 'MultiPoint',
      coordinates: [
        [minimumLongitude, minimumLatitude],
        [maximumLongitude, maximumLatitude],
      ],
    };
    const projection = window.d3.geoMercator()
      .fitExtent(
        [[PADDING, PADDING], [WIDTH - PADDING, HEIGHT - PADDING]],
        fitPoints
      )
      .clipExtent([[0, 0], [WIDTH, HEIGHT]]);
    const path = window.d3.geoPath(projection);
    const svg = window.d3.select(svgElement)
      .attr('viewBox', `0 0 ${WIDTH} ${HEIGHT}`)
      .attr('preserveAspectRatio', 'xMidYMid meet');
    const viewport = svg.append('g');

    viewport.append('path')
      .datum(window.d3.geoGraticule10())
      .attr('d', path)
      .attr('fill', 'none')
      .attr('stroke', '#d9e2ec')
      .attr('stroke-width', 0.65)
      .attr('aria-hidden', 'true');

    try {
      const response = await fetch(root.dataset.momentsMapBasemap, {
        credentials: 'same-origin',
      });
      if (!response.ok) {
        throw new Error(`basemap request failed: ${response.status}`);
      }
      const topology = await response.json();
      if (window.topojson && topology.objects?.countries) {
        viewport.append('path')
          .datum(window.topojson.feature(topology, topology.objects.countries))
          .attr('d', path)
          .attr('fill', '#f4f7f9')
          .attr('stroke', '#9fb3c8')
          .attr('stroke-width', 0.8)
          .attr('vector-effect', 'non-scaling-stroke')
          .attr('aria-hidden', 'true');
      }
    } catch (error) {
      if (details) {
        details.textContent = 'The offline basemap did not load. Dots and the list below still work.';
      }
    }

    viewport.selectAll('.moments-map-pin')
      .data([...places].sort((left, right) => right.visits - left.visits))
      .join('circle')
      .attr('class', 'moments-map-pin')
      .attr('cx', place => projection([place.lon, place.lat])[0])
      .attr('cy', place => projection([place.lon, place.lat])[1])
      .attr('fill', place => SOURCE_COLORS[place.source] || '#555555')
      .attr('fill-opacity', 0.72)
      .attr('stroke', '#ffffff')
      .attr('stroke-width', 1.6)
      .attr('stroke-dasharray', place => place.source === 'instagram' ? '2 1' : null)
      .attr('tabindex', 0)
      .attr('role', 'img')
      .attr('aria-label', place => (
        `${SOURCE_LABELS[place.source] || place.source}，${placeName(place)}，`
        + `${formatNumber(place.visits)} visits, `
        + `${place.first} to ${place.last}`
      ))
      .append('title')
      .text(place => (
        `${SOURCE_LABELS[place.source] || place.source} · ${placeName(place)} · `
        + `${formatNumber(place.visits)} visits · `
        + `${place.first} – ${place.last}`
      ));
    const pins = viewport.selectAll('.moments-map-pin');

    let selectedYear = '';
    const selectedSources = new Set(
      sourceFilters.filter(filter => filter.checked).map(filter => filter.value)
    );
    let currentTransform = window.d3.zoomIdentity;
    let hideTimer = null;
    const radius = place => 4 + 3.2 * Math.sqrt(Math.max(1, activeVisits(place)));
    const activeMoments = place => (
      selectedYear
        ? (place.moments || []).filter(moment => String(moment.at).startsWith(selectedYear))
        : (place.moments || [])
    );
    function activeVisits(place) {
      return selectedYear ? activeMoments(place).length : place.visits;
    }
    const isVisible = place => (
      selectedSources.has(place.source)
      && (!selectedYear || place.years.has(selectedYear))
    );

    const tooltipText = place => {
      const count = activeVisits(place);
      return [
        SOURCE_LABELS[place.source] || place.source,
        placeName(place),
        place.city || 'Unknown city',
        `${formatNumber(count)} visits`,
        `${place.first} to ${place.last}`,
      ].join(' · ');
    };

    const clearTooltip = () => {
      if (tooltip) {
        tooltip.hidden = true;
        tooltip.replaceChildren();
      }
    };
    const cancelTooltipHide = () => {
      if (hideTimer !== null) {
        window.clearTimeout(hideTimer);
        hideTimer = null;
      }
    };
    const scheduleTooltipHide = () => {
      cancelTooltipHide();
      hideTimer = window.setTimeout(clearTooltip, 180);
    };
    const showPlace = (place, target) => {
      cancelTooltipHide();
      const summary = tooltipText(place);
      if (details) {
        const moments = activeMoments(place);
        details.textContent = moments.length
          ? `${summary} · ${moments[0].at} · ${moments[0].text || 'No text summary'}`
          : summary;
      }
      if (!tooltip) {
        return;
      }
      const heading = document.createElement('strong');
      heading.className = 'db mb1';
      heading.textContent = placeName(place);
      const metadata = document.createElement('span');
      metadata.className = 'db gray mb1';
      metadata.textContent = [
        SOURCE_LABELS[place.source] || place.source,
        place.city || 'Unknown city',
        `${formatNumber(activeVisits(place))} visits`,
        `${place.first} – ${place.last}`,
      ].join(' · ');
      tooltip.replaceChildren(heading, metadata);
      activeMoments(place).forEach(moment => {
        const line = document.createElement(moment.url ? 'a' : 'span');
        line.className = 'db mt1';
        line.textContent = `${moment.at} · ${moment.text || 'No text summary'}`;
        if (moment.url) {
          line.href = moment.url;
          line.target = '_blank';
          line.rel = 'noopener noreferrer';
        }
        tooltip.append(line);
      });
      tooltip.style.maxHeight = '20rem';
      tooltip.style.overflowY = 'auto';
      tooltip.hidden = false;

      const x = currentTransform.applyX(number(target.getAttribute('cx')));
      const y = currentTransform.applyY(number(target.getAttribute('cy')));
      const frameRect = frame.getBoundingClientRect();
      const scaleX = frameRect.width / WIDTH;
      const scaleY = frameRect.height / HEIGHT;
      const left = Math.min(
        Math.max(8, x * scaleX + 12),
        Math.max(8, frameRect.width - 260)
      );
      const top = Math.min(
        Math.max(8, y * scaleY + 12),
        Math.max(8, frameRect.height - 120)
      );
      tooltip.style.left = `${left}px`;
      tooltip.style.top = `${top}px`;
    };

    pins
      .on('pointerenter focus', (event, place) => {
        window.d3.select(event.currentTarget)
          .attr('stroke', '#111111')
          .attr('stroke-width', 2.4 / currentTransform.k);
        showPlace(place, event.currentTarget);
      })
      .on('pointerleave blur', event => {
        window.d3.select(event.currentTarget)
          .attr('stroke', '#ffffff')
          .attr('stroke-width', 1.6 / currentTransform.k);
        scheduleTooltipHide();
      })
      .on('keydown', event => {
        if (event.key === 'Escape') {
          clearTooltip();
          event.currentTarget.blur();
        }
      });
    tooltip?.addEventListener('pointerenter', cancelTooltipHide);
    tooltip?.addEventListener('pointerleave', scheduleTooltipHide);

    const zoom = window.d3.zoom()
      .scaleExtent([1, 40])
      .on('zoom', event => {
        currentTransform = event.transform;
        viewport.attr('transform', currentTransform);
        pins
          .attr('r', place => radius(place) / currentTransform.k)
          .attr('stroke-width', 1.6 / currentTransform.k);
        clearTooltip();
      });
    svg.call(zoom);

    const update = () => {
      pins
        .attr('display', place => isVisible(place) ? null : 'none')
        .attr('r', place => radius(place) / currentTransform.k);
      root.querySelectorAll('[data-moments-map-table-row]').forEach(row => {
        const place = places.find(candidate => candidate.key === row.dataset.momentsMapTableRow);
        row.hidden = !place || !isVisible(place);
      });
      const visible = places.filter(isVisible);
      const cities = new Set(visible.map(place => place.city).filter(Boolean));
      const visits = visible.reduce((total, place) => total + activeVisits(place), 0);
      const pinCount = root.querySelector('[data-moments-map-pin-count]');
      const cityCount = root.querySelector('[data-moments-map-city-count]');
      const visitCount = root.querySelector('[data-moments-map-visit-count]');
      if (pinCount) pinCount.textContent = formatNumber(visible.length);
      if (cityCount) cityCount.textContent = formatNumber(cities.size);
      if (visitCount) visitCount.textContent = formatNumber(visits);
      clearTooltip();
      if (details) {
        const sourceSummary = [...selectedSources]
          .map(source => SOURCE_LABELS[source] || source)
          .join('、');
        details.textContent = selectedSources.size === 0
          ? 'No sources selected.'
          : `${selectedYear ? `${selectedYear} · ` : ''}${sourceSummary}`
            + `Showing ${formatNumber(visible.length)} places and ${formatNumber(visits)} records.`;
      }
    };

    yearFilter?.addEventListener('change', () => {
      selectedYear = yearFilter.value;
      update();
    });
    sourceFilters.forEach(filter => {
      filter.addEventListener('change', () => {
        if (filter.checked) {
          selectedSources.add(filter.value);
        } else {
          selectedSources.delete(filter.value);
        }
        update();
      });
    });
    resetButton?.addEventListener('click', () => {
      svg.transition()
        .duration(REDUCED_MOTION ? 0 : 180)
        .call(zoom.transform, window.d3.zoomIdentity);
    });
    update();
  };

  const initializeWithFallback = root => {
    initialize(root).catch(() => {
      const details = root.querySelector('[data-moments-map-details]');
      if (details) {
        details.textContent = 'The map failed to start. Place details below still work.';
      }
    });
  };
  const scan = root => {
    if (root.matches?.('[data-moments-map]')) {
      initializeWithFallback(root);
    }
    root.querySelectorAll?.('[data-moments-map]').forEach(initializeWithFallback);
  };
  scan(document);
  document.addEventListener('wechat:lazy-loaded', event => {
    scan(event.detail?.root || document);
  });
})();
