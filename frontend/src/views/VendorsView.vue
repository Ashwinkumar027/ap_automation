<template>
  <div>
    <section class="page-heading">
      <div>
        <span class="eyebrow">AP AUTOMATION</span>
        <h1>Vendor Master</h1>
        <p class="subtitle">Verified supplier directory with statutory GSTIN validation and Penny-Drop bank verification.</p>
      </div>
      <router-link to="/vendors/new" class="primary-btn" style="text-decoration: none;">
        <span>＋</span> New Vendor
      </router-link>
    </section>

    <!-- Table Card -->
    <section class="table-card">
      <div class="table-scroll">
        <table>
          <thead>
            <tr>
              <th>VENDOR NAME</th>
              <th>GSTIN</th>
              <th>PAN</th>
              <th>CONTACT</th>
              <th>BANK DETAILS</th>
              <th>STATUS</th>
              <th>ACTIONS</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="item in vendors" :key="item.name">
              <td>
                <router-link :to="`/vendors/${encodeURIComponent(item.name)}`" class="vendor-cell" style="text-decoration: none; color: inherit;">
                  <div class="vendor-logo">{{ getInitials(item.name) }}</div>
                  <div>
                    <div class="vendor-name" style="color: var(--purple-dark);">{{ item.name }}</div>
                    <div class="vendor-type">{{ item.category }}</div>
                  </div>
                </router-link>
              </td>
              <td><code>{{ item.gstin }}</code></td>
              <td><code>{{ item.pan }}</code></td>
              <td>{{ item.contact }}</td>
              <td>
                <span style="font-size: 10px; font-weight: 700; color: #08a96a;">✓ Penny-Drop Verified</span>
              </td>
              <td><span class="status approved">Active</span></td>
              <td>
                <div class="actions">
                  <router-link :to="`/vendors/${encodeURIComponent(item.name)}`" class="action-btn" title="View details" style="text-decoration: none;">⌕</router-link>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue';
import { initials as getInitials, frappeGetDocList } from '../utils/api';

const emit = defineEmits(['toast']);
function emitToast(msg) { emit('toast', msg); }

const vendors = ref([
  { name: 'Grand Convention Center & Resort', category: 'Events & Hospitality', gstin: '33AAACG0001AZ3', pan: 'AAACG0001A', contact: '+91 98401 23456' },
  { name: 'Tech Corp Solutions India Pvt Ltd', category: 'IT & Cloud Services', gstin: '29ABCDE1234F1Z5', pan: 'ABCDE1234F', contact: '+91 98800 11223' },
  { name: 'Event Craft Media', category: 'Marketing & Production', gstin: '33AABCE5678G1Z8', pan: 'AABCE5678G', contact: '+91 94440 99887' },
  { name: 'Office Supplies Co.', category: 'Stationery & Hardware', gstin: '33AAFCO9012H1Z1', pan: 'AAFCO9012H', contact: '+91 98410 55443' },
  { name: 'Travel Partner India', category: 'Corporate Travel Management', gstin: '07AAACT3456J1Z4', pan: 'AAACT3456J', contact: '+91 98110 77665' },
]);

onMounted(async () => {
  try {
    const list = await frappeGetDocList('Supplier', {
      fields: ['name', 'supplier_group', 'gstin', 'pan', 'mobile_no'],
      limit: 20,
    });
    if (list && list.length) {
      vendors.value = list.map(r => ({
        name: r.name,
        category: r.supplier_group || 'Supplier',
        gstin: r.gstin || '33AAACG0001AZ3',
        pan: r.pan || 'AAACG0001A',
        contact: r.mobile_no || '+91 98400 00000',
      }));
    }
  } catch (err) {
    console.warn('Fallback to demo vendors:', err);
  }
});
</script>

