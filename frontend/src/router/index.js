import { createRouter, createWebHistory } from 'vue-router';
import DashboardView from '../views/DashboardView.vue';

// Petty Cash (Lane 1)
import PettyCashView from '../views/PettyCashView.vue';
import PettyCashFormView from '../views/PettyCashFormView.vue';

// Vendor Invoice Claims (Lane 3A / 3B)
import VendorClaimsView from '../views/VendorClaimsView.vue';
import VendorClaimDetailView from '../views/VendorClaimDetailView.vue';

// Employee Reimbursements (Lane 2)
import EmployeeClaimsView from '../views/EmployeeClaimsView.vue';
import EmployeeClaimFormView from '../views/EmployeeClaimFormView.vue';

// Vendor Master
import VendorsView from '../views/VendorsView.vue';
import VendorFormView from '../views/VendorFormView.vue';

// Purchase Orders & GRN
import PurchaseOrdersView from '../views/PurchaseOrdersView.vue';
import PurchaseOrderFormView from '../views/PurchaseOrderFormView.vue';

// Event Spends (Lane 4)
import EventSpendsView from '../views/EventSpendsView.vue';
import EventSpendsFormView from '../views/EventSpendsFormView.vue';

// Payment Batches & Banking (Lane 5)
import PaymentBatchesView from '../views/PaymentBatchesView.vue';
import PaymentBatchDetailView from '../views/PaymentBatchDetailView.vue';

// Reports & Analytics Hub
import ReportsView from '../views/ReportsView.vue';
import ReportDetailView from '../views/ReportDetailView.vue';

// Settings
import SettingsView from '../views/SettingsView.vue';

const routes = [
  { path: '/', redirect: '/vendor-claims' },
  { path: '/dashboard', name: 'Dashboard', component: DashboardView },

  // Petty Cash (Lane 1)
  { path: '/petty-cash', name: 'PettyCash', component: PettyCashView },
  { path: '/petty-cash/new', name: 'NewPettyCash', component: PettyCashFormView },
  { path: '/petty-cash/:id', name: 'PettyCashDetail', component: PettyCashFormView },

  // Vendor Invoice Claims (Lane 3A / 3B)
  { path: '/vendor-claims', name: 'VendorClaims', component: VendorClaimsView },
  { path: '/vendor-claims/:id', name: 'VendorClaimDetail', component: VendorClaimDetailView },

  // Employee Reimbursements (Lane 2)
  { path: '/employee-claims', name: 'EmployeeClaims', component: EmployeeClaimsView },
  { path: '/employee-claims/new', name: 'NewEmployeeClaim', component: EmployeeClaimFormView },
  { path: '/employee-claims/:id', name: 'EmployeeClaimDetail', component: EmployeeClaimFormView },

  // Vendor Master
  { path: '/vendors', name: 'Vendors', component: VendorsView },
  { path: '/vendors/new', name: 'NewVendor', component: VendorFormView },
  { path: '/vendors/:id', name: 'VendorDetail', component: VendorFormView },

  // Purchase Orders & GRN
  { path: '/purchase-orders', name: 'PurchaseOrders', component: PurchaseOrdersView },
  { path: '/purchase-orders/new', name: 'NewPurchaseOrder', component: PurchaseOrderFormView },
  { path: '/purchase-orders/:id', name: 'PurchaseOrderDetail', component: PurchaseOrderFormView },
  { path: '/grn', name: 'GRN', component: PurchaseOrdersView },

  // Event Spends (Lane 4)
  { path: '/event-spends', name: 'EventSpends', component: EventSpendsView },
  { path: '/event-spends/new', name: 'NewEventMaster', component: EventSpendsFormView },
  { path: '/event-spends/:id', name: 'EventDetail', component: EventSpendsFormView },

  // Payment Batches & Banking (Lane 5)
  { path: '/payment-batches', name: 'PaymentBatches', component: PaymentBatchesView },
  { path: '/payment-batches/new', name: 'NewPaymentBatch', component: PaymentBatchDetailView },
  { path: '/payment-batches/:id', name: 'PaymentBatchDetail', component: PaymentBatchDetailView },

  // Reports
  { path: '/reports', name: 'Reports', component: ReportsView },
  { path: '/reports/:slug', name: 'ReportDetail', component: ReportDetailView },

  // Settings
  { path: '/settings', name: 'Settings', component: SettingsView },

  // Fallback
  { path: '/:pathMatch(.*)*', redirect: '/vendor-claims' },
];

const router = createRouter({
  history: createWebHistory('/ap/'),
  routes,
  scrollBehavior() {
    return { top: 0 };
  },
});

export default router;
