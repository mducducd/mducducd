import torch

import torch.nn as nn

class LSTM_VAE(torch.nn.Module):

  def __init__(self, vocab_size, embed_size, hidden_size, latent_size, num_layers=1):
    super(LSTM_VAE, self).__init__()

    self.device = "cuda" if torch.cuda.is_available() else "cpu"

    # Variables
    self.num_layers = num_layers
    self.lstm_factor = num_layers
    self.vocab_size = vocab_size
    self.embed_size = embed_size
    self.hidden_size = hidden_size
    self.latent_size = latent_size

   # X: bsz * seq_len * vocab_size 
    # Embedding
    self.embed = torch.nn.Linear(in_features= self.vocab_size , out_features=self.embed_size)

    #    X: bsz * seq_len * vocab_size 
    #    X: bsz * seq_len * embed_size

    # Encoder Part
    self.encoder_lstm = torch.nn.LSTM(input_size= self.embed_size,hidden_size= self.hidden_size, batch_first=True, num_layers= self.num_layers)
    self.mean = torch.nn.Linear(in_features= self.hidden_size * self.lstm_factor, out_features= self.latent_size)
    self.log_variance = torch.nn.Linear(in_features= self.hidden_size * self.lstm_factor, out_features= self.latent_size)

    # Decoder Part
                                        
    self.init_hidden_decoder = torch.nn.Linear(in_features= self.latent_size, out_features= self.hidden_size * self.lstm_factor)
    self.decoder_lstm = torch.nn.LSTM(input_size= self.embed_size, hidden_size= self.hidden_size, batch_first = True, num_layers = self.num_layers)
    self.output = torch.nn.Linear(in_features= self.hidden_size * self.lstm_factor, out_features= self.vocab_size)
    self.log_softmax = torch.nn.LogSoftmax(dim=1)
    self.layernorm_init = nn.LayerNorm(73)

    self.get_initial_state = nn.Sequential(
        nn.Linear(73, 73),
        nn.Tanh(),
        nn.Linear(73, 2 * self.num_layers * self.hidden_size),
    )
  def init_hidden(self, batch_size):
    hidden_cell = torch.zeros(self.num_layers, batch_size, self.hidden_size).to(self.device)
    state_cell = torch.zeros(self.num_layers, batch_size, self.hidden_size).to(self.device)
    return (hidden_cell, state_cell)

  def get_embedding(self, x):
    x_embed = self.embed(x)
    
    # Total length for pad_packed_sequence method = maximum sequence length
    maximum_sequence_length = x_embed.size(1)

    return x_embed, maximum_sequence_length

  def encoder(self, packed_x_embed,total_padding_length, hidden_encoder, init, lengths):

    # pad the packed input.
    init = self.get_initial_state(self.layernorm_init(init))
    init_hidden, init_cell = init.view(-1, 2, self.num_layers, self.hidden_size).permute(1, 2, 0, 3).contiguous()
    packed_output_encoder, hidden_encoder = self.encoder_lstm(packed_x_embed, (init_hidden, init_cell))

    # packed_output_encoder, hidden_encoder = self.encoder_lstm(packed_x_embed, hidden_encoder)
    output_encoder, _ = torch.nn.utils.rnn.pad_packed_sequence(packed_output_encoder, batch_first=True, total_length= total_padding_length)

    # Extimate the mean and the variance of q(z|x)
    mean = self.mean(hidden_encoder[0])
    log_var = self.log_variance(hidden_encoder[0])
    std = torch.exp(0.5 * log_var)   # e^(0.5 log_var) = var^0.5
    
    # Generate a unit gaussian noise.
    batch_size = output_encoder.size(0)
    seq_len = output_encoder.size(1)
    noise = torch.randn(batch_size, self.latent_size).to(self.device)
    
    z = noise * std + mean

    return z, mean, log_var, hidden_encoder


  def decoder(self, z, packed_x_embed, total_padding_length=None):

    hidden_decoder = self.init_hidden_decoder(z)
    hidden_decoder = (hidden_decoder, hidden_decoder)

    # pad the packed input.
    packed_output_decoder, hidden_decoder = self.decoder_lstm(packed_x_embed,hidden_decoder) 
    output_decoder, _ = torch.nn.utils.rnn.pad_packed_sequence(packed_output_decoder, batch_first=True, total_length= total_padding_length)


    x_hat = self.output(output_decoder)
    # A trick to apply binary cross entropy by using cross entropy loss. 
    neg_x_hat = (1 - x_hat)
        
    binary_x_hat = torch.stack((x_hat, neg_x_hat), dim=3).contiguous()
    # print(binary_logits.size())
    binary_x_hat = binary_x_hat.view(-1, 2)

    binary_x_hat = self.log_softmax(binary_x_hat)
    return (binary_x_hat, hidden_decoder)

  

  def forward(self, x,sentences_length,hidden_encoder, init, lengths):
    
    """
      x : bsz * seq_len
    
      hidden_encoder: ( num_lstm_layers * bsz * hidden_size, num_lstm_layers * bsz * hidden_size)

    """
    # Get Embeddings
    x_embed, maximum_padding_length = self.get_embedding(x)

    # Packing the input
    packed_x_embed = torch.nn.utils.rnn.pack_padded_sequence(input= x_embed, lengths= sentences_length, batch_first=True, enforce_sorted=False)


    # Encoder
    z, mean, log_var, hidden_encoder = self.encoder(packed_x_embed, maximum_padding_length, hidden_encoder, init, lengths)

    # Decoder
    binary_x_hat,hidden_decoder = self.decoder(z, packed_x_embed, maximum_padding_length)
    
    # hidden_decoder = self.init_hidden_decoder(z)
    # hidden_decoder = (hidden_decoder, hidden_decoder)
    
    packed_x_embed = torch.nn.utils.rnn.pack_padded_sequence(input= x_embed, lengths= sentences_length, batch_first=True, enforce_sorted=False)
    packed_output_decoder,hidden_decoder = self.decoder_lstm(packed_x_embed,hidden_decoder)
    output, _ = torch.nn.utils.rnn.pad_packed_sequence(packed_output_decoder, batch_first=True)
    
    # x_hat = self.output(output)

    return output, binary_x_hat, mean, log_var, z, hidden_encoder
  
# model = LSTM_VAE(vocab_size = 118, embed_size = 300, hidden_size = 256, latent_size = 16).cuda()
# states = model.init_hidden(4) 

# length = torch.tensor([90])
# length = torch.tensor([90]).repeat(4)
# x = torch.rand(4, 90, 118).cuda()
# x_hat, binary_x_hat, mean, log_var, z, hidden_encoder = model(x, length, states)
# print(x_hat.shape)