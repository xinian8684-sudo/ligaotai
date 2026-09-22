import { createRouter, createWebHistory } from 'vue-router'

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', name: 'books', component: () => import('./pages/BooksPage.vue') },
    { path: '/settings', name: 'settings', component: () => import('./pages/SettingsPage.vue') },
    {
      // 书内页面共用一个外壳（导航栏），见 layouts/BookLayout.vue
      path: '/b/:name',
      component: () => import('./layouts/BookLayout.vue'),
      props: true,
      children: [
        { path: '', redirect: (to) => `/b/${String(to.params.name)}/pipeline` },
        { path: 'pipeline', name: 'pipeline', component: () => import('./pages/PipelinePage.vue'), props: true },
        { path: 'pipeline/entities', name: 'entities', component: () => import('./pages/EntitiesPage.vue'), props: true },
        { path: 'pipeline/threads', name: 'threads', component: () => import('./pages/ThreadsPage.vue'), props: true },
        { path: 'panorama', name: 'panorama', component: () => import('./pages/PanoramaPage.vue'), props: true },
        { path: 'scenes', name: 'scenes', component: () => import('./pages/ScenesPage.vue'), props: true },
        { path: 'archive', name: 'archive', component: () => import('./pages/ArchivePage.vue'), props: true },
        { path: 'contradictions', name: 'contradictions', component: () => import('./pages/ContradictionsPage.vue'), props: true },
      ],
    },
    { path: '/:pathMatch(.*)*', redirect: '/' },
  ],
})
