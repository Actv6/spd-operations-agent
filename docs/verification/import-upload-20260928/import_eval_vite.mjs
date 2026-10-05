import { createServer } from '/Users/ac/Documents/ChatGPT/agent项目学习/frontend/node_modules/vite/dist/node/index.js';
const server = await createServer({root:'/Users/ac/Documents/ChatGPT/agent项目学习/frontend', server:{host:'127.0.0.1',port:4181,strictPort:true,proxy:{'/api':{target:'http://127.0.0.1:8011',changeOrigin:false}}}});
await server.listen(); console.log('Import acceptance UI http://127.0.0.1:4181');
