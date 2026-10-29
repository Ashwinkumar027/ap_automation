<template>
  <div class="app-layout">
    <Sidebar @support="showToast('Support desk contacted: support@aioniongroup.com')" />

    <main class="main">
      <Topbar
        @search="handleGlobalSearch"
        @notify="showToast('You are caught up — no new pending notifications.')"
        @help="showToast('AP Automation help: filter claims, trigger approvals, or disburse Friday batches.')"
      />

      <router-view @toast="showToast" />
    </main>

    <!-- Global Toast Notification -->
    <div class="toast" :class="{ show: toastMessage }">
      {{ toastMessage }}
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue';
import Sidebar from './components/Sidebar.vue';
import Topbar from './components/Topbar.vue';

const toastMessage = ref('');
let toastTimer = null;

function showToast(msg) {
  toastMessage.value = msg;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => {
    toastMessage.value = '';
  }, 3000);
}

function handleGlobalSearch(query) {
  // Can be propagated to current active view if needed
}
</script>

