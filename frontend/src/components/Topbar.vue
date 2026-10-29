<template>
  <header class="topbar">
    <label class="global-search">
      <span>⌕</span>
      <input
        ref="searchInputRef"
        v-model="searchQuery"
        placeholder="Search invoices, vendor, PO number, amount..."
        aria-label="Global search"
        @input="$emit('search', searchQuery)"
      />
      <span class="shortcut">⌘ K</span>
    </label>

    <div class="top-actions">
      <button class="icon-btn notification" title="Notifications" @click="$emit('notify')">♧</button>
      <button class="icon-btn help-top" title="Help" @click="$emit('help')">?</button>
      <a href="/app" title="Switch to Frappe Desk (/app)" class="user">
        <div class="avatar">{{ userInitials }}</div>
        <span>{{ userName }}</span>
        <span>⌄</span>
      </a>
    </div>
  </header>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue';
import { initials } from '../utils/api';

defineEmits(['search', 'notify', 'help']);

const searchInputRef = ref(null);
const searchQuery = ref('');

const userName = computed(() => window.user_fullname || 'Administrator');
const userInitials = computed(() => initials(userName.value));

function handleKeyDown(e) {
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
    e.preventDefault();
    if (searchInputRef.value) {
      searchInputRef.value.focus();
    }
  }
}

onMounted(() => {
  window.addEventListener('keydown', handleKeyDown);
});

onUnmounted(() => {
  window.removeEventListener('keydown', handleKeyDown);
});
</script>

