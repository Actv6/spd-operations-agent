import {fileURLToPath} from 'node:url';
const front=fileURLToPath(new URL('../../../frontend/',import.meta.url));
const {createServer}=await import(front+'node_modules/vite/dist/node/index.js');
const {default:react}=await import(front+'node_modules/@vitejs/plugin-react/dist/index.js');
const server=await createServer({configFile:false,root:front,plugins:[react()],server:{host:'127.0.0.1',port:4182,strictPort:true,proxy:{'/api':{target:'http://127.0.0.1:8012',changeOrigin:false}}}});
await server.listen();console.log('Isolated V1.2 preview http://127.0.0.1:4182');
