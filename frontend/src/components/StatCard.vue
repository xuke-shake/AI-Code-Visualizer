<script setup lang="ts">
defineProps<{
  title: string
  value: string | number
  caption: string
}>()
</script>

<template>
  <section class="page-card stat-card">
    <div class="stat-head">
      <span class="badge">{{ title }}</span>
      <span class="stat-caption">{{ caption }}</span>
    </div>
    <strong>{{ value }}</strong>
  </section>
</template>

<style scoped>
.stat-card {
  padding: 6px 8px;
  display: grid;
  gap: 4px;
  min-height: 56px;
}

.stat-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 4px;
}

strong {
  font-size: 18px;
  line-height: 1;
}

.stat-caption {
  color: var(--muted);
  font-size: 10px;
  text-align: right;
}
</style>
