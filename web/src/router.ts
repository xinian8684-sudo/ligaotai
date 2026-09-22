import { createRouter, createWebHistory } from 'vue-router'

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', name: 'books', component: () => import('./pages/BooksPage.vue') },
    { path: '/settings', name: 'settings', component: () => import('./pages/SettingsPage.vue') },
    { path: '/b/:name/pipeline', name: 'pipeline', component: () => import('./pages/PipelinePage.vue'), props: true },
    { path: '/b/:name/pipeline/entities', name: 'entities', component: () => import('./pages/EntitiesPage.vue'), props: true },
    { path: '/b/:name/pipeline/threads', name: 'threads', component: () => import('./pages/ThreadsPage.vue'), props: true },
    { path: '/b/:name/panorama', name: 'panorama', component: () => import('./pages/PanoramaPage.vue'), props: true },
    { path: '/b/:name/scenes', name: 'scenes', component: () => import('./pages/ScenesPage.vue'), props: true },
    { path: '/b/:name/archive', name: 'archive', component: () => import('./pages/ArchivePage.vue'), props: true },
    { path: '/b/:name/contradictions', name: 'contradictions', component: () => import('./pages/ContradictionsPage.vue'), props: true },
    { path: '/:pathMatch(.*)*', redirect: '/' },
  ],
})
