<template>
  <article class="kpi">
    <div class="kpi-icon" :class="color">
      {{ icon }}
    </div>
    <div>
      <div class="kpi-number">{{ value }}</div>
      <div class="kpi-label">{{ label }}</div>
      <div class="kpi-trend" :style="trendColor ? { color: trendColor } : {}">
        {{ trend }}
      </div>
    </div>
    <svg class="spark" viewBox="0 0 80 28" fill="none">
      <path :d="sparkPath" :stroke="sparkColor" stroke-width="2" stroke-linecap="round" />
    </svg>
  </article>
</template>

<script setup>
defineProps({
  icon: { type: String, default: '▤' },
  color: { type: String, default: 'purple' },
  value: { type: [String, Number], default: 0 },
  label: { type: String, default: '' },
  trend: { type: String, default: '' },
  trendColor: { type: String, default: '' },
  sparkColor: { type: String, default: '#7655ff' },
  sparkPath: {
    type: String,
    default: 'M1 23 C10 23 10 12 18 16 S30 22 39 10 S53 18 61 8 S73 5 79 2',
  },
});
</script>

