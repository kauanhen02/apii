const axios = require("axios");
const { exec } = require('child_process');

const url = "https://api.bcb.gov.br/dados/serie/bcdata.sgs.1/dados?formato=json";

async function obterCotacaoDolarPTAXVenda() {
  try {
    const response = await axios.get(url);
    const dados = response.data;
    const dataAtual = new Date().toLocaleDateString();

    let valorEncontrado = null;

    for (let i = 0; i < dados.length; i++) {
      if (dataAtual === dados[i].data) {
        valorEncontrado = dados[i].valor;
        break;
      } 
    }

    for (let o = dados.length - 1; o >= 0; o--) {
      if (dataAtual !== dados[o].data) {
        valorEncontrado = dados[o].valor;
        break;
      } 
    }
    

    if (valorEncontrado !== null) {
      const resultado = { Valor: valorEncontrado };
      const jsonResultado = JSON.stringify(resultado);
      console.log(jsonResultado);

      // Executar npm start após obter a cotação do dólar
      console.log("Executando npm start após obter a cotação do dólar...");
      exec('npm start', (error, stdout, stderr) => {
        if (error) {
          console.error(`Erro ao executar npm start: ${error.message}`);
          return;
        }
        if (stderr) {
          console.error(`Erro ao executar npm start: ${stderr}`);
          return;
        }
        console.log(`npm start executado com sucesso: ${stdout}`);
      });
    } else {
      console.log(JSON.stringify({ error: "Cotação não encontrada para a data atual." }));
    }
  } catch (error) {
    console.error("Erro ao obter a cotação:", error);
  }
}

// Execute a função a cada 10 segundos
setInterval(obterCotacaoDolarPTAXVenda, 10000); // 10 segundos em milissegundos
