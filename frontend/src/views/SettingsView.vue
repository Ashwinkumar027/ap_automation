<template>
  <div>
    <section class="page-heading">
      <div>
        <span class="eyebrow">AP AUTOMATION</span>
        <h1>Settings & Configurations</h1>
        <p class="subtitle">Approval matrix rules, IDFC Bank credentials, and system batch preferences.</p>
      </div>
      <button class="primary-btn" @click="emitToast('Settings saved successfully.')">
        Save Preferences
      </button>
    </section>

    <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 16px;">
      <div style="padding: 22px; border: 1px solid #e7e8f8; border-radius: 19px; background: rgba(255,255,255,0.9); box-shadow: var(--shadow);">
        <h3 style="margin: 0 0 16px; font-size: 14px; font-weight: 800;">Banking & Payment Gateway</h3>
        <div class="form-grid">
          <div class="field full">
            <label>Disbursement Bank</label>
            <input value="IDFC FIRST Bank (Corporate Direct Integration)" disabled />
          </div>
          <div class="field">
            <label>Corporate Customer ID</label>
            <input value="CORP-IDFC-998822" />
          </div>
          <div class="field">
            <label>Default Payment Mode</label>
            <select>
              <option>NEFT / RTGS</option>
              <option>IMPS (Express Disbursal)</option>
              <option>Internal Transfer (IDFC to IDFC)</option>
            </select>
          </div>
        </div>
      </div>

      <div style="padding: 22px; border: 1px solid #e7e8f8; border-radius: 19px; background: rgba(255,255,255,0.9); box-shadow: var(--shadow);">
        <h3 style="margin: 0 0 16px; font-size: 14px; font-weight: 800;">Approval Matrix Thresholds</h3>
        <div class="form-grid">
          <div class="field">
            <label>Admin L1 Threshold (₹)</label>
            <input value="50,000" />
          </div>
          <div class="field">
            <label>Admin L2 Threshold (₹)</label>
            <input value="2,50,000" />
          </div>
          <div class="field full">
            <label>Mandatory Director Approval (₹)</label>
            <input value="Above ₹2,50,000 (Requires Accounts Director)" />
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
const emit = defineEmits(['toast']);
function emitToast(msg) { emit('toast', msg); }
</script>

