import torch
import torch.nn as nn
import torch.nn.utils.spectral_norm as spectralnorm
from matplotlib import pyplot 
import numpy as np

class TSA(nn.Module):
	def __init__(self, in_c):
		super(TSA, self).__init__()

		self.in_c = in_c
		self.q_conv = spectralnorm(nn.Conv3d(in_c, in_c//8, 1, 1, 0))
		self.k_conv = spectralnorm(nn.Conv3d(in_c, in_c//8, 1, 1, 0))
		self.v_conv = spectralnorm(nn.Conv3d(in_c, in_c, 1, 1, 0))
		self.gamma = nn.Parameter(torch.zeros(1))
		self.softmax = nn.Softmax(dim=2)

	def forward(self, x):

		b, c, t, h, w = x.size()
		key = self.k_conv(x).permute(0,3,4,1,2).contiguous().view(b*h*w, -1, t)
		query = self.q_conv(x).permute(0,3,4,1,2).contiguous().view(b*h*w, -1, t).transpose(2,1)
		value = self.v_conv(x).permute(0,3,4,1,2).contiguous().view(b*h*w, -1, t).transpose(2,1)
		scores = torch.matmul(query, key)

		attention = self.softmax(scores)
		out = torch.matmul(attention, value)
		out = out.view(b, h, w, -1, t).permute(0, 3, 4, 1, 2)
		out = self.gamma * out + x

		return out


class SSA(nn.Module):
	def __init__(self, in_c):
		super(SSA, self).__init__()

		self.in_c = in_c
		self.q_conv = spectralnorm(nn.Conv3d(in_c, in_c//8, 1, 1, 0))
		self.k_conv = spectralnorm(nn.Conv3d(in_c, in_c//8, 1, 1, 0))
		self.v_conv = spectralnorm(nn.Conv3d(in_c, in_c, 1, 1, 0))
		self.gamma = nn.Parameter(torch.zeros(1))
		self.softmax = nn.Softmax(dim=2)

	def forward(self, x):

		b, c, t, h, w = x.size()
		key = self.k_conv(x).transpose(2,1).contiguous().view(b*t, -1, h*w)
		query = self.q_conv(x).transpose(2,1).contiguous().view(b*t, -1, h*w).transpose(2,1)
		value = self.v_conv(x).transpose(2,1).contiguous().view(b*t, -1, h*w).transpose(2,1)
		scores = torch.matmul(query, key)

		attention = self.softmax(scores)
		out = torch.matmul(attention, value)
		out = out.view(b, h, w, -1, t).permute(0, 3, 4, 1, 2)
		out = self.gamma * out + x

		return out


class FSA(nn.Module):
	def __init__(self, in_c):
		super(FSA, self).__init__()

		self.tsa = TSA(in_c)
		self.ssa = SSA(in_c)

	def forward(self, x):

		h = self.tsa(x)
		h = self.ssa(h)

		return h


class G3(nn.Module):
	def __init__(self, in_cs, in_cv, in_ct, out_c, mode, k_s, k_t, s_s, s_t, p_s, p_t):
		super(G3, self).__init__()

		if mode == '3d':
			self.conv_v = nn.Sequential(
				spectralnorm(nn.ConvTranspose3d(in_cv, out_c, (k_t,k_s,k_s), (s_t,s_s,s_s), (p_t,p_s,p_s))),
				nn.BatchNorm3d(out_c),
				nn.ReLU(True)
			)

		elif mode == '2p1d':
			self.conv_v = nn.Sequential(
				spectralnorm(nn.ConvTranspose3d(in_cv, out_c, (1,k_s,k_s), (1,s_s,s_s), (0,p_s,p_s))),
				nn.BatchNorm3d(out_c),
				nn.ReLU(True),
				spectralnorm(nn.ConvTranspose3d(out_c, out_c, (k_t,1,1), (s_t,1,1), (p_t,0,0))),
				nn.BatchNorm3d(out_c),
				nn.ReLU(True)
			)

		elif mode == '1p2d':
			self.conv_v = nn.Sequential(
				spectralnorm(nn.ConvTranspose3d(in_cv, out_c, (k_t,1,1), (s_t,1,1), (p_t,0,0))),
				nn.BatchNorm3d(out_c),
				nn.ReLU(True),
				spectralnorm(nn.ConvTranspose3d(out_c, out_c, (1,k_s,k_s), (1,s_s,s_s), (0,p_s,p_s))),
				nn.BatchNorm3d(out_c),
				nn.ReLU(True)
			)

		else:
			raise NotImplementedError

		self.conv_s = nn.Sequential(
			spectralnorm(nn.ConvTranspose3d(in_cs, out_c, (1,k_s,k_s), (1,s_s,s_s), (0,p_s,p_s))),
			nn.BatchNorm3d(out_c),
			nn.ReLU(True)
		)
		

		self.conv_t = nn.Sequential(
			spectralnorm(nn.ConvTranspose3d(in_ct, out_c, (k_t,1,1), (s_t,1,1), (p_t,0,0))),
			nn.BatchNorm3d(out_c),
			nn.ReLU(True)
		)

	def forward(self, h_s, h_v, h_t):

		h_v = self.conv_v(h_v)
		h_s = self.conv_s(h_s)
		h_t = self.conv_t(h_t)

		h_t_r = h_t.repeat(1, 1, 1, h_v.size(3), h_v.size(4))
		h_v = h_v + h_t_r
		h_s_r = h_s.repeat(1, 1, h_v.size(2), 1, 1)
		h_v = torch.cat([h_s_r, h_v], 1)

		return h_s, h_v, h_t

# Disentangling into foreground and background instead of appearance
class G4(nn.Module):
	def __init__(self, in_cs, in_cv, in_ct, out_c, mode, k_s, k_t, s_s, s_t, p_s, p_t):
		super(G4, self).__init__()
        #args.d_za, args.d_zm, args.ch_g, args.g_mode, args.use_attention
		self.count=0
		if mode == '3d':
			self.conv_v = nn.Sequential(
				spectralnorm(nn.ConvTranspose3d(in_cv, out_c, (k_t,k_s,k_s), (s_t,s_s,s_s), (p_t,p_s,p_s))),
				nn.BatchNorm3d(out_c),
				nn.ReLU(True)
			)

		elif mode == '2p1d':
			self.conv_v = nn.Sequential(
				spectralnorm(nn.ConvTranspose3d(in_cv, out_c, (1,k_s,k_s), (1,s_s,s_s), (0,p_s,p_s))),
				nn.BatchNorm3d(out_c),
				nn.ReLU(True),
				spectralnorm(nn.ConvTranspose3d(out_c, out_c, (k_t,1,1), (s_t,1,1), (p_t,0,0))),
				nn.BatchNorm3d(out_c),
				nn.ReLU(True)
			)

		elif mode == '1p2d':
			self.conv_v = nn.Sequential(
				spectralnorm(nn.ConvTranspose3d(in_cv, out_c, (k_t,1,1), (s_t,1,1), (p_t,0,0))),
				nn.BatchNorm3d(out_c),
				nn.ReLU(True),
				spectralnorm(nn.ConvTranspose3d(out_c, out_c, (1,k_s,k_s), (1,s_s,s_s), (0,p_s,p_s))),
				nn.BatchNorm3d(out_c),
				nn.ReLU(True)
			)

		else:
			raise NotImplementedError
		'''	
		self.conv_s = nn.Sequential(
			spectralnorm(nn.ConvTranspose3d(in_cs, out_c, (1,k_s,k_s), (1,s_s,s_s), (0,p_s,p_s))),
			nn.BatchNorm3d(out_c),
			nn.ReLU(True)
		)
        
		torch.nn.ConvTranspose3d(in_channels, out_channels, kernel_size, stride=1, padding=0,
								 output_padding=0, groups=1, bias=True, dilation=1, padding_mode='zeros')
		'''
		self.conv_fg = nn.Sequential(
			spectralnorm(nn.ConvTranspose3d(in_cs, out_c, (1,k_s,k_s), (1,s_s,s_s), (0,p_s,p_s))),
			nn.BatchNorm3d(out_c),
			nn.ReLU(True)
		)

		self.conv_bg = nn.Sequential(
			spectralnorm(nn.ConvTranspose3d(in_cs, out_c, (1,k_s,k_s), (1,s_s,s_s), (0,p_s,p_s))),
			nn.BatchNorm3d(out_c),
			nn.ReLU(True)
		)

		self.conv_t = nn.Sequential(
			spectralnorm(nn.ConvTranspose3d(in_ct, out_c, (k_t,1,1), (s_t,1,1), (p_t,0,0))),
			nn.BatchNorm3d(out_c),
			nn.ReLU(True)
		)

		self.conv_mask = nn.Sequential(
			spectralnorm(nn.ConvTranspose3d(in_ct, 1, (k_t,k_s,k_s), (s_t,s_s,s_s), (p_t,p_s,p_s))),
			nn.BatchNorm3d(1),
			nn.Sigmoid()
		)
	# G4AN_masking__v3_final
	
	def forward(self, h_fg, h_bg, h_v, h_t, h_tm):
		#h_tm temporal volume from previous block for computing the  mask	
		h_v = self.conv_v(h_v)
		h_fg = self.conv_fg(h_fg)
		h_t = self.conv_t(h_t)
		h_bg = self.conv_bg(h_bg)
		h_tm = self.conv_mask(h_tm)				#mask

		#mask = h_tm.cpu().data.numpy()
		#mask = 1 -mask
		#mask = np.clip(mask,0.0,1.0)
		#mask = (mask * 255).astype(np.uint8)
		#mask = (1-mask)
		#print('mask_shape', mask.shape,  np.min(mask), np.max(mask))
		#pyplot.imsave('/media/vplab/Sonam_HDD/sonam-arti/Unconditional_Video_genration/g4an-3gpu/evaluation/masks'+'/mask_'+ str(self.count)+'.jpg', mask[0,0,3,:,:], cmap=pyplot.cm.gray)
		#self.count = self.count + 1
		h_t_r = h_t.repeat(1, 1, 1, h_v.size(3), h_v.size(4))
		#Add masking for foreground and background
		h_v = h_v + h_t_r             
		#repeat the mask across channel
		h_tm = h_tm.repeat(1, h_v.size(1), 1,1,1)
		#print('h_mask_r', h_mask_r.shape)
		h_fg_r = h_fg.repeat(1, 1, h_v.size(2), 1, 1)
		h_fg_r = h_tm * h_fg_r
		
		#h_fg_p = h_fg_r + h_t_r 
		#h_v = torch.cat([h_fg_r, h_v], 1)
		h_bg_r = h_bg.repeat(1, 1, h_v.size(2), 1, 1)
		h_bg_r = (1 - h_tm) * h_bg_r
		h_fbt_p = h_bg_r + h_fg_r
		#h_v = h_v + h_t_r			# adding temporal connection
		
		h_v = torch.cat([h_fbt_p, h_v], 1)
		return h_fg, h_bg, h_v, h_t, h_t_r
	'''
		# Ablation Study
		# 1. without GF, GB, GT
		# 2. without Gf 
	def forward(self, h_fg, h_bg, h_v, h_t, h_tm):
		#h_tm temporal volume from previous block for computing the  mask
			
		h_v = self.conv_v(h_v)
		#h_fg = self.conv_fg(h_fg)
		h_t = self.conv_t(h_t)
		h_bg = self.conv_bg(h_bg)
		h_tm = self.conv_mask(h_tm)				#mask

		h_t_r = h_t.repeat(1, 1, 1, h_v.size(3), h_v.size(4))
		#Add masking for foreground and background
		h_v = h_v + h_t_r             
		#repeat the mask across channel
		h_tm = h_tm.repeat(1, h_v.size(1), 1,1,1)
		
		
		#h_fg_p = h_fg_r + h_t_r 
		#h_v = torch.cat([h_fg_r, h_v], 1)
		h_bg_r = h_bg.repeat(1, 1, h_v.size(2), 1, 1)
		h_bg_r = (1 - h_tm) * h_bg_r
		#h_fbt_p = h_bg_r + h_fg_r
		#h_v = h_v + h_t_r			# adding temporal connection
		h_fbt_p = h_bg_r 
		h_v = torch.cat([h_fbt_p, h_v], 1)
		
		return h_fg, h_bg, h_v, h_t, h_t_r

		'''	
if __name__ == '__main__':

	x_v = torch.randn(4, 128, 4, 4, 4)
	x_fg = torch.randn(4, 128, 1, 4, 4)
	x_bg = torch.randn(4, 128, 1, 4, 4)
	x_t = torch.randn(4, 128, 4, 1, 1)

	net = G3(128, 64, '1p2', 4, 4, 2, 2, 1, 1)
	out = net(x_fg, x_bg, x_v, x_t)
	print(out.size())