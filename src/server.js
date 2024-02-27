const axios = require("axios");

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
    } else {
      console.log(JSON.stringify({ error: "Cotação não encontrada para a data atual." }));
    }
  } catch (error) {
    console.error("Erro ao obter a cotação:", error);
  }
}

// Execute a função a cada 10 segundos
setInterval(obterCotacaoDolarPTAXVenda, 10000); // 10 segundos em milissegundos
